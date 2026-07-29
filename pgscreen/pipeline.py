"""
Screening pipeline: read the Zotero CSV, screen each paper, write one row each.

Design notes:

- Resumable. Every completed row is flushed immediately and keyed by the Zotero
  item key, so an interrupted run picks up where it stopped instead of paying
  for the same papers twice. This matters more than it sounds: a full pass over
  160 papers at high effort is not something you want to repeat because the
  laptop slept.
- Concurrent, but bounded. Papers are independent, so they run in a thread pool.
- Failures are rows, not exceptions. A paper that errors is written with its
  error recorded, which keeps the output aligned with the input and makes the
  failures visible instead of silently absent.
"""

import csv
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import criteria, rubric
from .providers import BackendError

# Bibliographic columns copied from the input, then the model's output.
META_COLUMNS = [
    "Key", "Author", "Publication Year", "Title", "Publication Title",
    "Volume", "Issue", "Pages", "DOI", "File Attachments",
]

CRITERION_COLUMNS = []
for _n in sorted(criteria.CRITERIA):
    _short = criteria.CRITERIA[_n]["short"]
    CRITERION_COLUMNS += [
        f"C{_n} {_short}",
        f"C{_n} Comment",
        f"C{_n} Evidence",
        f"C{_n} Reasoning",
    ]

SCORE_COLUMNS = []
for _key, _label, _q, _a in rubric.DIMENSIONS:
    SCORE_COLUMNS += [
        f"Score ({_label})",
        f"Comment ({_label})",
        f"Evidence ({_label})",
        f"Reasoning ({_label})",
    ]

# Explicit rubric-key -> column-header map. Derived headers would silently
# reshuffle the CSV whenever a rubric description was reworded.
SCOPE_COLUMNS = {
    "disease": "Specific Disease(s)",
    "modeling_approach": "Specific Modeling Approach(es)",
    "social_context": "Specific Social Contexts",
    "population": "Specific Populations",
    "geography": "Specific Geographical Location",
    "time_period": "Specific Time Periods",
    "data_source": "Specific Data Sources",
}
assert set(SCOPE_COLUMNS) == {k for k, _ in rubric.SCOPE_FIELDS}, \
    "SCOPE_COLUMNS is out of sync with rubric.SCOPE_FIELDS"

OUTPUT_COLUMNS = (
    META_COLUMNS
    + ["Decision", "Decision Rationale", "Failed Criteria",
       "Model Decision", "Model Decision Rationale", "Decision Mismatch"]
    + CRITERION_COLUMNS
    + ["Type", "Type Evidence", "Keywords"]
    + [SCOPE_COLUMNS[key] for key, _ in rubric.SCOPE_FIELDS]
    + ["Specific Other"]
    + SCORE_COLUMNS
    + ["Challenges", "Recommendations", "Screening Notes",
       "Model", "Rubric Version", "Status", "Error"]
)


def first_attachment(value):
    """The first usable path from Zotero's File Attachments field.

    Zotero separates multiple attachments with a semicolon, but a semicolon can
    also occur *inside* a filename -- titles like "...decision making; [La
    utilidad de los modelos...]" are common in bilingual journals, and splitting
    naively truncates the path mid-name and reports a present file as missing.
    So try the whole string first and only split if that fails.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if Path(raw).is_file():
        return raw
    for part in raw.split(";"):
        part = part.strip()
        if part and Path(part).is_file():
            return part
    return raw.split(";")[0].strip()


def load_papers(csv_path):
    """Read the Zotero export. Returns rows that have a resolvable PDF, plus a
    list of (key, title, reason) for those that do not."""
    papers, skipped = [], []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            attachment = first_attachment(row.get("File Attachments"))
            record = {
                "key": (row.get("Key") or "").strip(),
                "author": (row.get("Author") or "").strip(),
                "year": (row.get("Publication Year") or "").strip(),
                "title": (row.get("Title") or "").strip(),
                "journal": (row.get("Publication Title") or "").strip(),
                "volume": (row.get("Volume") or "").strip(),
                "issue": (row.get("Issue") or "").strip(),
                "pages": (row.get("Pages") or "").strip(),
                "doi": (row.get("DOI") or "").strip(),
                "pdf": attachment,
            }
            if not attachment:
                skipped.append((record["key"], record["title"], "no attachment listed"))
            elif not Path(attachment).is_file():
                skipped.append((record["key"], record["title"], "file missing on disk"))
            else:
                papers.append(record)
    return papers, skipped


def already_done(output_csv):
    """Zotero keys already present in the output, so a rerun can skip them."""
    path = Path(output_csv)
    if not path.is_file():
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {
            (row.get("Key") or "").strip()
            for row in csv.DictReader(fh)
            if (row.get("Key") or "").strip() and row.get("Status") == "ok"
        }


def drop_failed_rows(output_csv):
    """Rewrite a results file keeping only successful rows.

    Results are appended, and `already_done` only counts successes -- so a plain
    rerun retries the failures but leaves their old rows in place, giving two
    rows for the same paper. Clearing them first keeps the CSV one-row-per-paper,
    which is what every downstream count assumes.

    Returns (kept, dropped). The previous file is saved alongside as .bak.csv.
    """
    path = Path(output_csv)
    if not path.is_file():
        return 0, 0
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or OUTPUT_COLUMNS)
        rows = list(reader)
    kept = [r for r in rows if r.get("Status") == "ok"]
    dropped = len(rows) - len(kept)
    if not dropped:
        return len(kept), 0
    shutil.copy2(path, path.with_suffix(".bak.csv"))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)
    return len(kept), dropped


class ResultWriter:
    """Append-only CSV writer, safe to call from worker threads."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._fh, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore"
        )
        if self.path.stat().st_size == 0:
            self._writer.writeheader()
            self._fh.flush()

    def write(self, row):
        with self._lock:
            self._writer.writerow(row)
            self._fh.flush()  # survive an interrupted run

    def close(self):
        self._fh.close()


def _flatten(paper, parsed, model, status="ok", error=""):
    row = {
        "Key": paper["key"],
        "Author": paper["author"],
        "Publication Year": paper["year"],
        "Title": paper["title"],
        "Publication Title": paper["journal"],
        "Volume": paper["volume"],
        "Issue": paper["issue"],
        "Pages": paper["pages"],
        "DOI": paper["doi"],
        "File Attachments": paper["pdf"],
        "Model": model,
        "Rubric Version": rubric.RUBRIC_VERSION,
        "Status": status,
        "Error": error,
    }
    if not parsed:
        return row

    # The authoritative decision is derived from the two criterion scores, not
    # taken from the model. Cheaper models apply the stated rule inconsistently
    # -- measured at 11/67 on Haiku 4.5, always in the permissive direction --
    # and a rule that is a pure function of two integers has no business being
    # delegated. The model's own call is kept alongside: where the two differ,
    # the model read the paper as a whole against its own scores, and that
    # disagreement is worth a human glance.
    verdicts = {}
    for number in sorted(criteria.CRITERIA):
        block = parsed.get(f"criterion_{number}") or {}
        verdict = block.get("verdict", "")
        if verdict:
            verdicts[number] = verdict
        short = criteria.CRITERIA[number]["short"]
        row[f"C{number} {short}"] = verdict
        row[f"C{number} Comment"] = block.get("comment", "")
        row[f"C{number} Evidence"] = block.get("evidence", "")
        row[f"C{number} Reasoning"] = block.get("reasoning", "")

    decision, rationale = rubric.decide(verdicts)
    row["Failed Criteria"] = ",".join(
        str(n) for n, v in sorted(verdicts.items()) if v == "not met"
    )
    model_decision = parsed.get("decision", "")
    row["Decision"] = decision
    row["Decision Rationale"] = rationale
    row["Model Decision"] = model_decision
    row["Model Decision Rationale"] = parsed.get("decision_rationale", "")
    row["Decision Mismatch"] = (
        "yes" if model_decision and model_decision != decision else ""
    )
    row["Type"] = parsed.get("publication_type", "")
    row["Type Evidence"] = parsed.get("publication_type_evidence", "")
    keywords = parsed.get("keywords") or []
    row["Keywords"] = ", ".join(keywords) if isinstance(keywords, list) else keywords

    for key, _desc in rubric.SCOPE_FIELDS:
        row[SCOPE_COLUMNS[key]] = parsed.get(f"scope_{key}", "")
    row["Specific Other"] = parsed.get("scope_other", "")

    for key, label, _q, _a in rubric.DIMENSIONS:
        block = parsed.get(key) or {}
        row[f"Score ({label})"] = block.get("score", "")
        row[f"Comment ({label})"] = block.get("comment", "")
        row[f"Evidence ({label})"] = block.get("evidence", "")
        row[f"Reasoning ({label})"] = block.get("reasoning", "")

    for field, column in (("challenges", "Challenges"),
                          ("recommendations", "Recommendations")):
        value = parsed.get(field) or []
        row[column] = (
            "\n".join(f"- {item}" for item in value)
            if isinstance(value, list) else str(value)
        )
    row["Screening Notes"] = parsed.get("screening_notes", "")
    return row


def run_batch(papers, backend, writer, poll=30, progress=print):
    """Screen via the Batches API: half the token cost, asynchronous.

    Suited to this workload because papers are independent and the result is
    read hours later regardless. Results come back in arbitrary order, so they
    are keyed by the Zotero item key rather than matched by position.
    """
    system = rubric.build_system()
    schema = rubric.build_schema()
    by_key = {p["key"]: p for p in papers}

    jobs = [(p["key"], rubric.build_user_text(p), p["pdf"]) for p in papers]
    progress(f"Submitting {len(jobs)} papers as one batch ...")
    batch_id = backend.submit_batch(jobs, system, schema)
    progress(f"Batch id: {batch_id}\n"
             f"  Safe to interrupt -- rerun with --resume-batch {batch_id}\n")

    return collect_batch(batch_id, by_key, backend, writer, poll, progress)


def collect_batch(batch_id, by_key, backend, writer, poll=30, progress=print):
    """Poll a batch to completion, then write its results."""
    while True:
        status, counts = backend.batch_status(batch_id)
        if status == "ended":
            break
        progress(f"  [{status}] succeeded={counts['succeeded']} "
                 f"errored={counts['errored']} processing={counts['processing']}")
        time.sleep(poll)

    totals = {"ok": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
              "cache_read": 0, "cache_write": 0}
    seen = set()
    for custom_id, parsed, usage, error in backend.batch_results(batch_id):
        paper = by_key.get(custom_id)
        if paper is None:          # a key from some other run's batch
            continue
        seen.add(custom_id)
        label = (paper["title"] or custom_id)[:56]
        if error:
            writer.write(_flatten(paper, None, backend.model,
                                  status="failed", error=error))
            totals["failed"] += 1
            progress(f"  FAILED  {label} -- {error[:80]}")
            continue
        writer.write(_flatten(paper, parsed, backend.model))
        totals["ok"] += 1
        for key in ("input_tokens", "output_tokens", "cache_read", "cache_write"):
            totals[key] += usage.get(key, 0)
        marks = "".join(
            {"met": ".", "not met": "X", "unclear": "?"}.get(
                (parsed.get(f"criterion_{n}") or {}).get("verdict"), "-")
            for n in sorted(criteria.CRITERIA)
        )
        decision, _ = rubric.decide({
            n: v for n in sorted(criteria.CRITERIA)
            if (v := (parsed.get(f"criterion_{n}") or {}).get("verdict"))
        })
        progress(f"  {decision:9} [{marks}]  {label}")

    missing = set(by_key) - seen
    for key in missing:
        writer.write(_flatten(by_key[key], None, backend.model, status="failed",
                              error="no result returned in the batch"))
        totals["failed"] += 1
    if missing:
        progress(f"  {len(missing)} paper(s) had no result in the batch")
    return totals


def run(papers, backend, writer, workers=4, progress=print):
    system = rubric.build_system()
    schema = rubric.build_schema()
    totals = {"ok": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0,
              "cache_read": 0, "cache_write": 0}
    lock = threading.Lock()

    def screen_one(paper):
        started = time.monotonic()
        parsed, usage = backend.screen(
            system, rubric.build_user_text(paper), paper["pdf"], schema
        )
        return parsed, usage, time.monotonic() - started

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(screen_one, p): p for p in papers}
        for done, future in enumerate(as_completed(futures), 1):
            paper = futures[future]
            label = (paper["title"] or paper["key"])[:60]
            try:
                parsed, usage, elapsed = future.result()
            except Exception as exc:  # noqa: BLE001 - a bad paper must not stop the run
                writer.write(_flatten(paper, None, backend.model,
                                      status="failed", error=f"{type(exc).__name__}: {exc}"))
                with lock:
                    totals["failed"] += 1
                progress(f"[{done}/{len(futures)}] FAILED  {label} -- {exc}")
                continue

            writer.write(_flatten(paper, parsed, backend.model))
            with lock:
                totals["ok"] += 1
                for k in ("input_tokens", "output_tokens", "cache_read"):
                    totals[k] += usage.get(k, 0)
            marks = "".join(
                {"met": ".", "not met": "X", "unclear": "?"}.get(
                    (parsed.get(f"criterion_{n}") or {}).get("verdict"), "-")
                for n in sorted(criteria.CRITERIA)
            )
            verdicts = {
                n: (parsed.get(f"criterion_{n}") or {}).get("verdict")
                for n in sorted(criteria.CRITERIA)
            }
            decision, _ = rubric.decide(
                {n: v for n, v in verdicts.items() if v})
            progress(
                f"[{done}/{len(futures)}] {decision:9} [{marks}] "
                f"{elapsed:5.1f}s  {label}"
            )
    return totals
