#!/usr/bin/env python3
"""
full-screen.py -- automated full-text screening for the Pandemic Guidelines review.

Reads a Zotero CSV export, sends each paper's PDF to a model together with the
screening instrument in pgscreen/rubric.py, and writes one row per paper.

Setup
-----
  python -m venv venv
  venv\\Scripts\\activate            # Windows;  source venv/bin/activate elsewhere
  pip install -r requirements.txt

  Put your keys in .env:
      ANTHROPIC_API_KEY=sk-ant-...
      OPENAI_API_KEY=...             # only for --backend openai
      OPENAI_BASE_URL=...            # only if not api.openai.com
      SCREEN_MODEL=claude-sonnet-5   # one knob for either backend

Cost
----
PDF pages are expensive: ~3,750 input tokens each, measured on this corpus.
Check before you run --

  python full-screen.py --list-models      # cost of this run, per model
  python full-screen.py --dry-run          # estimate for the current settings

Model choice and --effort are the two big levers. The run is priced and
confirmed before any request is sent; --yes skips the prompt.

  Export the collection from Zotero as CSV to ./data/articles-full-screen.csv.
  The 'File Attachments' column must contain resolvable paths; --dry-run reports
  any that do not.

Usage
-----
  python full-screen.py --dry-run              # what would run, no API calls
  python full-screen.py --limit 3              # try three papers first
  python full-screen.py                        # the whole collection
  python full-screen.py --backend openai --model gpt-4o

Reruns skip papers already screened successfully, so an interrupted run resumes
rather than restarting. Use --fresh to start over.
"""

import argparse
import os
import sys
from pathlib import Path

from pgscreen import models, pipeline, rubric
from pgscreen.env import load_env
from pgscreen.providers import build_backend


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", default="./data/articles-full-screen.csv")
    ap.add_argument("--output", default="./results/articles-full-screen-results.csv")
    ap.add_argument("--backend", default="anthropic",
                    choices=["anthropic", "openai", "openai-compatible"])
    ap.add_argument("--model", default=None,
                    help="Model id. Overrides SCREEN_MODEL / ANTHROPIC_MODEL / "
                         "OPENAI_MODEL in .env. Run --list-models to see options "
                         "and their cost for this corpus.")
    ap.add_argument("--list-models", action="store_true",
                    help="Show the model registry with estimated cost, then exit.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the cost confirmation prompt.")
    ap.add_argument("--base-url", default=None,
                    help="OpenAI-compatible endpoint. Overrides OPENAI_BASE_URL.")
    ap.add_argument("--effort", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"],
                    help="Anthropic only. Reasoning depth (default: high).")
    ap.add_argument("--max-tokens", type=int, default=16000,
                    help="Output ceiling. Five criteria plus four quality "
                         "dimensions run ~4,700 tokens on a typical paper, but "
                         "long reviews overrun 8,000 and the whole paper is then "
                         "lost. Raising this costs nothing unless the tokens are "
                         "actually generated.")
    ap.add_argument("--workers", type=int, default=4,
                    help="Papers screened in parallel (default: 4).")
    ap.add_argument("--batch", action="store_true",
                    help="Submit via the Batches API: half the token cost, but "
                         "asynchronous (usually under an hour, 24h ceiling). "
                         "Worth it for a full corpus; pointless for --limit.")
    ap.add_argument("--resume-batch", metavar="BATCH_ID",
                    help="Collect a batch submitted by an earlier run.")
    ap.add_argument("--poll", type=int, default=30,
                    help="Seconds between batch status checks (default: 30).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Screen only the first N eligible papers.")
    ap.add_argument("--fresh", action="store_true",
                    help="Ignore existing results and rescreen everything.")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Rewrite the output keeping only successful rows, then "
                         "rescreen whatever is missing. Without this a rerun "
                         "appends a second row for each retried paper and the "
                         "CSV ends up with duplicate keys.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would happen without calling the API.")
    args = ap.parse_args()

    load_env()

    # Model resolution, cheapest lever first: --model, then SCREEN_MODEL in
    # .env (one knob for either backend), then the per-provider variable, then
    # the registry default.
    default_model = (
        args.model
        or os.environ.get("SCREEN_MODEL")
        or os.environ.get("ANTHROPIC_MODEL" if args.backend == "anthropic"
                          else "OPENAI_MODEL")
        or ("claude-sonnet-5" if args.backend == "anthropic" else "gpt-4o")
    )

    papers, skipped = pipeline.load_papers(args.input)
    print(f"Input:            {args.input}")
    print(f"Papers with PDFs: {len(papers)}")
    if skipped:
        print(f"Skipped:          {len(skipped)} (no resolvable PDF)")

    output = Path(args.output)
    if args.fresh and output.exists():
        backup = output.with_suffix(".bak.csv")
        output.replace(backup)
        print(f"--fresh: moved previous results to {backup}")

    if args.retry_failed and output.exists():
        kept, dropped = pipeline.drop_failed_rows(output)
        print(f"--retry-failed: kept {kept} successful row(s), "
              f"dropped {dropped} failed one(s) for rescreening")

    done = set() if args.fresh else pipeline.already_done(output)
    if done:
        print(f"Already screened: {len(done)} (will be skipped)")
    todo = [p for p in papers if p["key"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"To screen now:    {len(todo)}")
    print(f"Rubric version:   {rubric.RUBRIC_VERSION}")

    if args.list_models:
        reference = todo or papers
        print(f"\nCost of screening {len(reference)} papers, by model:")
        print(models.comparison_table(reference, args.backend))
        print("\nSet one with --model, or SCREEN_MODEL=<id> in .env.")
        print("Anthropic effort also moves cost: --effort medium is cheaper "
              "than the default high.")
        return 0

    batching = bool(args.batch or args.resume_batch)
    estimate = (models.estimate(todo, args.backend, default_model, batch=batching)
                if todo else None)
    if estimate:
        print()
        print(models.format_estimate(estimate, args.backend, default_model))

    if args.dry_run:
        print("\n--dry-run: no API calls made. First few papers:")
        for paper in todo[:5]:
            print(f"  {paper['key']}  {paper['title'][:70]}")
        if skipped:
            print("\nPapers without a usable PDF:")
            for key, title, reason in skipped[:10]:
                print(f"  {key or '(no key)'}  {title[:55]:57} [{reason}]")
            if len(skipped) > 10:
                print(f"  ... and {len(skipped) - 10} more")
        return 0

    if not todo:
        print("\nNothing to do.")
        return 0

    # Last chance to stop before spending. Skipped when non-interactive or --yes.
    if not args.yes and sys.stdin.isatty():
        shown = (f"~${estimate['cost']:.2f}" if estimate and estimate["cost"]
                 else "an unknown amount")
        how = " via the Batches API" if batching else ""
        answer = input(
            f"\nAbout to screen {len(todo)} papers with {default_model}{how}, "
            f"costing {shown}. Continue? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Stopped. Nothing spent. "
                  "Try --list-models to compare, or --limit N for a smaller run.")
            return 0

    backend_kwargs = {"model": default_model, "max_tokens": args.max_tokens}
    if args.backend == "anthropic":
        backend_kwargs["effort"] = args.effort
    else:
        backend_kwargs["base_url"] = args.base_url
    try:
        backend = build_backend(args.backend, **backend_kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCould not start the {args.backend} backend: {exc}", file=sys.stderr)
        return 1

    print(f"Backend:          {backend.name} / {backend.model}")
    if not backend.supports_native_pdf:
        print("                  (PDF text extracted locally -- see providers.py)")
    print(f"Workers:          {args.workers}\n")

    writer = pipeline.ResultWriter(output)
    try:
        if args.resume_batch:
            totals = pipeline.collect_batch(
                args.resume_batch, {p["key"]: p for p in todo}, backend, writer,
                poll=args.poll)
        elif args.batch:
            totals = pipeline.run_batch(todo, backend, writer, poll=args.poll)
        else:
            totals = pipeline.run(todo, backend, writer, workers=args.workers)
    finally:
        writer.close()

    print(f"\nScreened {totals['ok']} ok, {totals['failed']} failed.")
    total_in = (totals["input_tokens"] + totals["cache_read"]
                + totals["cache_write"])
    print(f"Tokens in:  {total_in:,}  "
          f"({totals['input_tokens']:,} fresh, {totals['cache_read']:,} cache read, "
          f"{totals['cache_write']:,} cache write)")
    print(f"Tokens out: {totals['output_tokens']:,}")
    rates = models.price(args.backend, default_model)
    if rates:
        spend = (
            totals["input_tokens"] / 1e6 * rates.input
            + totals["cache_read"] / 1e6 * rates.input * models.CACHE_READ_RATE
            + totals["cache_write"] / 1e6 * rates.input * models.CACHE_WRITE_RATE
            + totals["output_tokens"] / 1e6 * rates.output
        )
        if batching:
            spend *= models.BATCH_DISCOUNT
        basis = "introductory" if rates.intro else "list"
        print(f"Cost:       ~${spend:.2f} at {default_model} {basis} price"
              f"{' (batched)' if batching else ''}")
    print(f"Results: {output}")
    return 0 if totals["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
