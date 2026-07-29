"""
Model backends.

Both backends take the same input -- a rubric, a bibliographic record, and a PDF
-- and return the same parsed dict. Everything provider-specific (how a PDF is
attached, how JSON is constrained, what a retry looks like) lives here so the
pipeline never branches on provider.

The two differ in one way worth knowing about: Anthropic accepts the PDF as a
document, so the model sees layout, tables, and figures. Most OpenAI-compatible
endpoints do not, so that backend extracts text locally and sends that instead.
Scores are therefore not strictly comparable across backends -- treat a backend
switch as a new run, not a continuation.
"""

import base64
import json
import os
import re


class BackendError(RuntimeError):
    """Raised when a backend cannot produce a parsed result."""


def _strip_fences(text):
    """Some OpenAI-compatible servers wrap JSON in markdown despite being asked not to."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _first_json_object(text):
    """Recover the outermost JSON object from a response with stray prose."""
    start = text.find("{")
    if start == -1:
        raise BackendError(f"no JSON object in response: {text[:200]!r}")
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise BackendError("unterminated JSON object in response")


def parse_json(text):
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_first_json_object(text))


class AnthropicBackend:
    """Native PDF input plus schema-constrained output."""

    name = "anthropic"
    supports_native_pdf = True

    def __init__(self, model=None, api_key=None, max_tokens=8000, effort="high"):
        import anthropic

        from . import models as registry

        self._sdk = anthropic
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
        self.max_tokens = max_tokens
        # Older models reject `effort` with a 400 instead of ignoring it, so
        # whether to send it is a property of the model, not of the request.
        self.effort = effort if registry.supports_effort(self.model) else None
        # max_retries covers 429/5xx/connection errors with backoff.
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            max_retries=5,
            timeout=900.0,
        )

    def _output_config(self, schema):
        config = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            config["effort"] = self.effort
        return config

    def build_request(self, system, user_text, pdf_path, schema, text=None):
        """The request body, shared by the streaming and batch paths.

        Batching is worth having for a job like this -- every paper is
        independent, nothing is latency-sensitive, and the discount is 50% -- so
        the two paths must send byte-identical requests or results stop being
        comparable between runs.
        """
        content = []
        if text is None:
            with open(pdf_path, "rb") as fh:
                pdf_b64 = base64.standard_b64encode(fh.read()).decode("ascii")
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            })
        content.append({"type": "text", "text": user_text})
        return dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
            output_config=self._output_config(schema),
        )

    def parse_message(self, message):
        """Turn a completed Message into (parsed, usage). Shared by both paths."""
        if message.stop_reason == "refusal":
            raise BackendError("model declined to process this document")
        if message.stop_reason == "max_tokens":
            raise BackendError(
                f"output truncated at max_tokens={self.max_tokens}; raise it"
            )
        text = "".join(b.text for b in message.content if b.type == "text")
        if not text.strip():
            raise BackendError(f"empty response (stop_reason={message.stop_reason})")
        usage = {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "cache_read": getattr(message.usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(
                message.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return parse_json(text), usage

    def screen(self, system, user_text, pdf_path, schema, text=None):
        """Screen one paper.

        Supply `pdf_path` for full-text screening, or `text` when the document
        is already plain text. `user_text` carries the bibliographic context
        either way.
        """
        request = self.build_request(system, user_text, pdf_path, schema, text)

        # Streaming avoids HTTP timeouts on long documents at high effort.
        try:
            with self.client.messages.stream(**request) as stream:
                message = stream.get_final_message()
        except self._sdk.BadRequestError as exc:
            # Belt and braces for a model the registry does not know about:
            # drop effort once and retry rather than failing every paper.
            if self.effort and "effort" in str(exc).lower():
                self.effort = None
                request["output_config"] = self._output_config(schema)
                with self.client.messages.stream(**request) as stream:
                    message = stream.get_final_message()
            else:
                raise

        return self.parse_message(message)

    # ---------------- batch path ----------------
    #
    # Same requests, submitted asynchronously at half price. Worth it here
    # because every paper is independent and nothing is latency-sensitive.

    def submit_batch(self, jobs, system, schema):
        """jobs: iterable of (custom_id, user_text, pdf_path). Returns batch id."""
        requests = [
            {
                "custom_id": custom_id,
                "params": self.build_request(system, user_text, pdf_path, schema),
            }
            for custom_id, user_text, pdf_path in jobs
        ]
        return self.client.messages.batches.create(requests=requests).id

    def batch_status(self, batch_id):
        batch = self.client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        return batch.processing_status, {
            "succeeded": counts.succeeded, "errored": counts.errored,
            "processing": counts.processing, "canceled": counts.canceled,
            "expired": counts.expired,
        }

    def batch_results(self, batch_id):
        """Yield (custom_id, parsed, usage, error). Order is not guaranteed."""
        for entry in self.client.messages.batches.results(batch_id):
            custom_id = entry.custom_id
            result = entry.result
            if result.type != "succeeded":
                detail = getattr(result, "error", None)
                yield custom_id, None, {}, f"{result.type}: {detail}"
                continue
            try:
                parsed, usage = self.parse_message(result.message)
            except Exception as exc:  # noqa: BLE001
                yield custom_id, None, {}, f"{type(exc).__name__}: {exc}"
                continue
            yield custom_id, parsed, usage, None


class OpenAICompatBackend:
    """Any endpoint speaking the OpenAI chat-completions API.

    Covers OpenAI itself, OpenRouter, vLLM, Ollama, LM Studio, and most
    university-hosted gateways. PDF text is extracted client-side, because
    native document input is not part of the shared subset those servers agree
    on.
    """

    name = "openai-compatible"
    supports_native_pdf = False

    def __init__(self, model=None, api_key=None, base_url=None, max_tokens=8000,
                 max_pdf_chars=280_000):
        from openai import OpenAI

        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        self.max_tokens = max_tokens
        self.max_pdf_chars = max_pdf_chars
        self.client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL") or None,
            max_retries=5,
            timeout=900.0,
        )

    def _extract_text(self, pdf_path):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise BackendError(
                "the OpenAI-compatible backend needs pypdf for PDF text "
                "extraction: pip install pypdf"
            ) from exc

        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        text = "\n\n".join(pages).strip()
        if len(text) < 500:
            raise BackendError(
                "extracted almost no text -- the PDF is probably a scan. Use the "
                "Anthropic backend for this paper, or OCR it first."
            )
        truncated = len(text) > self.max_pdf_chars
        if truncated:
            text = text[:self.max_pdf_chars]
        return text, truncated

    def screen(self, system, user_text, pdf_path, schema, text=None):
        if text is not None:
            body, truncated = text, False
        else:
            body, truncated = self._extract_text(pdf_path)
        note = (
            "\n\n[Note: the extracted text was truncated at "
            f"{self.max_pdf_chars} characters. Say so in screening_notes.]"
            if truncated else ""
        )
        content = (
            f"{user_text}\n\n"
            f"--- BEGIN EXTRACTED FULL TEXT ---\n{body}\n"
            f"--- END EXTRACTED FULL TEXT ---{note}"
        )

        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
        # Prefer real schema enforcement; fall back through json_object to plain
        # text, since coverage varies widely across compatible servers.
        attempts = [
            {**kwargs, "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "screening", "strict": True,
                                "schema": schema},
            }},
            {**kwargs, "response_format": {"type": "json_object"}},
            kwargs,
        ]
        last_error = None
        for attempt in attempts:
            try:
                completion = self.client.chat.completions.create(**attempt)
                break
            except Exception as exc:  # noqa: BLE001 - server capability probing
                last_error = exc
        else:
            raise BackendError(f"all request forms rejected: {last_error}")

        text = completion.choices[0].message.content or ""
        if not text.strip():
            raise BackendError("empty response")

        usage = {}
        if completion.usage:
            usage = {
                "input_tokens": completion.usage.prompt_tokens,
                "output_tokens": completion.usage.completion_tokens,
                "cache_read": 0,
            }
        return parse_json(text), usage


def build_backend(name, **kwargs):
    if name == "anthropic":
        return AnthropicBackend(**kwargs)
    if name in ("openai", "openai-compatible"):
        return OpenAICompatBackend(**kwargs)
    raise ValueError(f"unknown backend {name!r}")
