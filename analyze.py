#!/usr/bin/env python3
"""
analyze.py -- summarise a full-text screening run.

  python analyze.py results/screening.csv
  python analyze.py results/screening.csv --show-excluded

Reports the decision split, which criteria did the excluding, the quality-score
distributions, and every row carrying a screening note or a decision mismatch --
those are the rows worth a human read first.

There is no comparison mode against Zotero collections. The collections that
carried prior screening decisions (1., 2., 3.x, 4., 5.) all sit under
`_deprecated` and encode a superseded round, so agreement against them measures
nothing. The current ground truth for the title/abstract stage is
rayyan-screened-export.csv, handled by analyze_abstracts.py.
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from pgscreen import criteria, rubric


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("results")
    ap.add_argument("--show-excluded", action="store_true",
                    help="List every excluded paper with its failed criteria.")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    if not Path(args.results).is_file():
        sys.exit(f"No such file: {args.results}")
    with open(args.results, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    # A rerun appends rather than replaces, so a retried paper can appear twice
    # -- once failed, once succeeded. Keep the successful row and count the
    # paper once, but say so rather than silently reconciling.
    by_key, duplicates = {}, 0
    for row in rows:
        key = row.get("Key") or f"__row{len(by_key)}"
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
            continue
        duplicates += 1
        if existing.get("Status") != "ok" and row.get("Status") == "ok":
            by_key[key] = row
    if duplicates:
        print(f"note: {duplicates} duplicate row(s) collapsed (a rerun appended "
              f"retries). Use --retry-failed next time to keep the file clean.\n")
    rows = list(by_key.values())
    ok = [r for r in rows if r.get("Status") == "ok"]

    print(f"{args.results}: {len(rows)} row(s), {len(ok)} ok, "
          f"{len(rows) - len(ok)} failed")
    if ok:
        versions = Counter(r.get("Rubric Version") for r in ok)
        models_used = Counter(r.get("Model") for r in ok)
        print(f"  rubric: {', '.join(sorted(filter(None, versions)))}")
        print(f"  model:  {', '.join(sorted(filter(None, models_used)))}")
    if not ok:
        return 0

    print("\n--- decision ---")
    for value, n in Counter(r.get("Decision") for r in ok).most_common():
        print(f"  {n:>4}  {value or '(blank)'}  {n / len(ok):>5.0%}")

    print("\n--- criterion verdicts ---")
    print(f"  {'criterion':36} {'met':>6} {'not met':>8} {'unclear':>8}")
    for n in sorted(criteria.CRITERIA):
        column = f"C{n} {criteria.CRITERIA[n]['short']}"
        c = Counter(r.get(column) for r in ok)
        print(f"  {n} {criteria.CRITERIA[n]['short']:34.34} {c.get('met', 0):>6} "
              f"{c.get('not met', 0):>8} {c.get('unclear', 0):>8}")

    excluded = [r for r in ok if r.get("Decision") == "exclude"]
    if excluded:
        print(f"\n--- what did the excluding ({len(excluded)} paper(s)) ---")
        tally = Counter()
        for r in excluded:
            for n in (r.get("Failed Criteria") or "").split(","):
                if n.strip():
                    tally[int(n)] += 1
        for n, count in sorted(tally.items()):
            print(f"  C{n} {criteria.CRITERIA[n]['short']:34.34} {count:>4}")

    print("\n--- quality scores ---")
    print(f"  {'dimension':40} {'0':>4} {'1':>4} {'2':>4}")
    for key, label, _q, _a in rubric.DIMENSIONS:
        c = Counter(r.get(f"Score ({label})") for r in ok)
        print(f"  {label:40} {c.get('0', 0):>4} {c.get('1', 0):>4} "
              f"{c.get('2', 0):>4}")

    print("\n--- publication type ---")
    for t, n in Counter(r.get("Type") for r in ok).most_common():
        print(f"  {n:>4}  {t}")

    uncertain = [r for r in ok if r.get("Decision") == "uncertain"]
    if uncertain:
        print(f"\n--- {len(uncertain)} uncertain, review these first ---")
        for r in uncertain[:args.show]:
            print(f"  {r['Title'][:62]}")
            print(f"      {r.get('Decision Rationale', '')[:110]}")

    mismatch = [r for r in ok if r.get("Decision Mismatch") == "yes"]
    if mismatch:
        print(f"\n--- {len(mismatch)} row(s) where the model's own call "
              f"disagreed with the rule ---")
        for r in mismatch[:args.show]:
            print(f"  rule={r['Decision']:9} model={r.get('Model Decision', ''):9} "
                  f"{r['Title'][:48]}")

    noted = [r for r in ok if (r.get("Screening Notes") or "").strip()]
    if noted:
        print(f"\n--- {len(noted)} row(s) with screening notes ---")
        for r in noted[:args.show]:
            print(f"  {r['Title'][:58]}")
            print(f"      {r['Screening Notes'][:140]}")

    if args.show_excluded and excluded:
        print(f"\n--- excluded papers ---")
        for r in excluded:
            print(f"  fails C{r.get('Failed Criteria', '?')}  {r['Title'][:60]}")

    failed = [r for r in rows if r.get("Status") != "ok"]
    if failed:
        print(f"\n--- {len(failed)} failure(s) ---")
        for r in failed[:args.show]:
            print(f"  {r.get('Title', '')[:58]}\n      {r.get('Error', '')[:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
