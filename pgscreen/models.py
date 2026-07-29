"""
Model registry and cost estimation.

Screening a 160-paper corpus is a real spend, and the difference between the
cheapest and dearest option here is a factor of five. The point of this module
is that you see that number before the run, not after it.

Prices are USD per million tokens and are cached, not fetched -- check the
provider's pricing page if a number looks stale, and edit the table.

Calibration (measured on 21 papers of this corpus, 197 pages, Anthropic
native-PDF input): 3,750 input tokens per PDF page and ~2,100 output tokens per
paper. PDF pages are dear because layout and figures are tokenised too; the
OpenAI-compatible backend extracts plain text and runs far cheaper per page,
but sees less.
"""

from datetime import date
from typing import NamedTuple

# Calibrated against a real invoice: 21 papers, ~198 pages, 901,584 input and
# 45,968 output tokens, billed at $5.12 on claude-opus-5.
TOKENS_PER_PDF_PAGE = 3950     # Anthropic native document input
TOKENS_PER_PAGE_TEXT = 1600    # local text extraction (1.13M chars / 197 pages
                               # at ~3.6 chars per token)
OUTPUT_TOKENS_PER_PAPER = 2200
RUBRIC_TOKENS = 5800           # the cacheable system prefix

# Cache multipliers on the input rate.
CACHE_READ_RATE = 0.10
CACHE_WRITE_RATE = 1.25

# The Batches API charges half of everything, in exchange for asynchrony.
BATCH_DISCOUNT = 0.50

# Rates are $ per million tokens. `intro` is a promotional rate with an expiry:
# quoting list price while a promotion is running overstates the bill by nearly
# half, and hardcoding the promotional rate would understate it the day after it
# ends -- so both are stored and the date decides.
ANTHROPIC_MODELS = {
    "claude-opus-5": {
        "input": 5.00, "output": 25.00,
        "note": "most capable; deepest reading",
    },
    "claude-opus-4-8": {
        "input": 5.00, "output": 25.00, "note": "previous Opus",
    },
    "claude-sonnet-5": {
        "input": 3.00, "output": 15.00,
        "intro": {"input": 2.00, "output": 10.00, "until": date(2026, 8, 31)},
        "note": "near-Opus on most work; good default",
    },
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00, "note": "previous Sonnet",
    },
    "claude-haiku-4-5": {
        "input": 1.00, "output": 5.00,
        "note": "cheapest; 200K ctx, no effort control",
    },
}

# Indicative only -- an OpenAI-compatible endpoint can be anything, including
# free local inference. Unknown models estimate tokens but not cost.
OPENAI_MODELS = {
    "gpt-4o":      {"input": 2.50, "output": 10.00, "note": ""},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "note": ""},
}

# Models that predate the effort parameter reject it outright with a 400 rather
# than ignoring it, so it cannot be sent speculatively.
NO_EFFORT_SUPPORT = {"claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-1"}


def supports_effort(model):
    return model not in NO_EFFORT_SUPPORT


class Rates(NamedTuple):
    input: float
    output: float
    note: str
    intro: bool          # a promotional rate is in effect today
    intro_until: object  # date it lapses, or None


def price(backend, model, on=None):
    """Effective rates for `model` today (or on a given date)."""
    table = ANTHROPIC_MODELS if backend == "anthropic" else OPENAI_MODELS
    entry = table.get(model)
    if entry is None:
        return None
    today = on or date.today()
    intro = entry.get("intro")
    if intro and today <= intro["until"]:
        return Rates(intro["input"], intro["output"], entry["note"],
                     True, intro["until"])
    return Rates(entry["input"], entry["output"], entry["note"], False, None)


def count_pages(pdf_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return None


def estimate(papers, backend, model, sample=25, batch=False):
    """Estimate tokens and cost for a set of papers.

    Pages are counted on a sample and extrapolated, because opening 160 PDFs
    just to print an estimate is its own small cost in time.
    """
    per_page = TOKENS_PER_PDF_PAGE if backend == "anthropic" else TOKENS_PER_PAGE_TEXT

    counted, pages = 0, 0
    for paper in papers[:sample]:
        n = count_pages(paper["pdf"])
        if n:
            counted += 1
            pages += n
    mean_pages = (pages / counted) if counted else 20.0

    n = len(papers)
    total_pages = mean_pages * n

    # The rubric is written to cache once and read back on every later paper;
    # the documents themselves are always fresh. Pricing those buckets
    # separately matters -- a write costs 1.25x and a read 0.1x.
    fresh = int(total_pages * per_page)
    cache_write = RUBRIC_TOKENS
    cache_read = RUBRIC_TOKENS * max(n - 1, 0)
    output_tokens = OUTPUT_TOKENS_PER_PAPER * n

    result = {
        "papers": n,
        "mean_pages": mean_pages,
        "pages_sampled_from": counted,
        "input_tokens": fresh + cache_write + cache_read,
        "output_tokens": output_tokens,
        "cost": None,          # what this run will actually cost
        "cost_streaming": None,  # the same run without batching
        "batch": batch,
        "rates": None,
    }
    rates = price(backend, model)
    if rates:
        streaming = (
            fresh / 1e6 * rates.input
            + cache_write / 1e6 * rates.input * CACHE_WRITE_RATE
            + cache_read / 1e6 * rates.input * CACHE_READ_RATE
            + output_tokens / 1e6 * rates.output
        )
        result["rates"] = rates
        result["cost_streaming"] = streaming
        result["cost"] = streaming * (BATCH_DISCOUNT if batch else 1.0)
    return result


def format_estimate(est, backend, model):
    lines = [
        f"Estimated for {est['papers']} papers "
        f"(mean {est['mean_pages']:.0f} pages, sampled {est['pages_sampled_from']}):",
        f"  input  ~{est['input_tokens']:,} tokens",
        f"  output ~{est['output_tokens']:,} tokens",
    ]
    if est["cost"] is None:
        lines.append(f"  cost   unknown -- {model!r} is not in the price table")
        return "\n".join(lines)

    rates = est["rates"]
    basis = "introductory" if rates.intro else "list"
    how = "batched" if est["batch"] else "streaming"
    lines.append(f"  cost   ~${est['cost']:.2f}   ({how}, {model} {basis} price: "
                 f"${rates.input:g}/${rates.output:g} per Mtok)")
    if rates.intro:
        lines.append(f"         introductory rate ends {rates.intro_until}; "
                     f"after that this run is "
                     f"~${est['cost'] / rates.input * ANTHROPIC_MODELS[model]['input']:.2f}")
    if est["batch"]:
        lines.append(f"         without --batch it would be "
                     f"~${est['cost_streaming']:.2f}")
    else:
        lines.append(f"         --batch would make it "
                     f"~${est['cost_streaming'] * BATCH_DISCOUNT:.2f} (asynchronous)")
    return "\n".join(lines)


def comparison_table(papers, backend="anthropic", batch=False):
    """What the same run would cost on each model, streaming and batched."""
    table = ANTHROPIC_MODELS if backend == "anthropic" else OPENAI_MODELS
    rows = []
    for model in table:
        est = estimate(papers, backend, model)
        rates = est["rates"]
        rows.append((model, est["cost_streaming"],
                     (est["cost_streaming"] or 0) * BATCH_DISCOUNT,
                     "intro" if rates and rates.intro else "",
                     table[model]["note"]))
    width = max(len(r[0]) for r in rows)
    out = ["", f"  {'model':{width}}   {'streaming':>10} {'--batch':>9}  "
               f"{'rate':>5}  note"]
    for model, streaming, batched, basis, note in sorted(
            rows, key=lambda r: r[1] or 0, reverse=True):
        a = f"${streaming:.2f}" if streaming is not None else "n/a"
        b = f"${batched:.2f}" if streaming is not None else "n/a"
        out.append(f"  {model:{width}}   {a:>10} {b:>9}  {basis:>5}  {note}")
    return "\n".join(out)
