#!/usr/bin/env python3
"""
compare_runs.py -- compare two screening runs over the same papers.

Used to decide whether a cheaper model can stand in for an expensive one:

  python compare_runs.py results/calibration-run.csv results/haiku-run.csv

The first file is treated as the reference. Reports decision agreement,
per-dimension score agreement, and the substance of what each run wrote --
because a model can match scores exactly while producing evidence too thin to
audit, and that is the failure mode worth catching.
"""

import argparse
import csv
import statistics
import sys
from collections import Counter
from pathlib import Path


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("Status") == "ok"]
    return {r["Key"]: r for r in rows}


def dimensions(row):
    return [k[7:-1] for k in row if k.startswith("Score (")]


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("reference", help="The run to compare against.")
    ap.add_argument("candidate", help="The run under test.")
    ap.add_argument("--show", type=int, default=12,
                    help="How many disagreeing papers to print (default 12).")
    args = ap.parse_args()

    for path in (args.reference, args.candidate):
        if not Path(path).is_file():
            sys.exit(f"No such file: {path}")

    ref, cand = load(args.reference), load(args.candidate)
    shared = [k for k in ref if k in cand]
    ref_name = Path(args.reference).stem
    cand_name = Path(args.candidate).stem

    print(f"reference: {ref_name}  ({len(ref)} papers)")
    print(f"candidate: {cand_name}  ({len(cand)} papers)")
    print(f"overlap:   {len(shared)} papers\n")
    if not shared:
        sys.exit("No papers in common -- nothing to compare.")

    dims = dimensions(ref[shared[0]])

    # --- decisions ---
    if any(ref[k].get("Decision") for k in shared):
        agree = sum(1 for k in shared
                    if ref[k].get("Decision") == cand[k].get("Decision"))
        print(f"--- decision agreement: {agree}/{len(shared)} "
              f"({agree/len(shared):.0%}) ---")
        pairs = Counter((ref[k].get("Decision"), cand[k].get("Decision"))
                        for k in shared)
        for (r, c), n in pairs.most_common():
            flag = "" if r == c else "   <-- differs"
            print(f"  {n:>3}  reference={r or '-':10} candidate={c or '-':10}{flag}")
        print()

    # --- per-dimension scores ---
    print(f"--- score agreement ---")
    print(f"  {'dimension':40} {'exact':>7} {'+-1':>7} {'mean diff':>10}")
    all_diffs = []
    for d in dims:
        diffs = []
        for k in shared:
            a, b = as_int(ref[k][f"Score ({d})"]), as_int(cand[k][f"Score ({d})"])
            if a is not None and b is not None:
                diffs.append(b - a)
        if not diffs:
            continue
        all_diffs += diffs
        exact = sum(1 for x in diffs if x == 0)
        within = sum(1 for x in diffs if abs(x) <= 1)
        mean = statistics.mean(diffs)
        arrow = "higher" if mean > 0.15 else ("lower" if mean < -0.15 else "")
        print(f"  {d:40} {exact:>3}/{len(diffs):<3} {within:>3}/{len(diffs):<3} "
              f"{mean:>+9.2f} {arrow}")
    if all_diffs:
        exact = sum(1 for x in all_diffs if x == 0)
        print(f"  {'OVERALL':40} {exact:>3}/{len(all_diffs):<3} "
              f"{sum(1 for x in all_diffs if abs(x)<=1):>3}/{len(all_diffs):<3} "
              f"{statistics.mean(all_diffs):>+9.2f}")

    # --- substance ---
    print(f"\n--- what each run wrote (mean characters) ---")
    def mean_len(rows, column):
        vals = [len((rows[k].get(column) or "").strip()) for k in shared]
        return statistics.mean(vals) if vals else 0

    print(f"  {'field':40} {ref_name[:14]:>14} {cand_name[:14]:>14}")
    for column in [f"Evidence ({d})" for d in dims] + \
                  ["Challenges", "Recommendations", "Screening Notes"]:
        if column not in ref[shared[0]]:
            continue
        print(f"  {column:40} {mean_len(ref, column):>14.0f} "
              f"{mean_len(cand, column):>14.0f}")

    nf_ref = sum(1 for k in shared for d in dims
                 if "none found" in (ref[k][f"Evidence ({d})"] or "").lower())
    nf_cand = sum(1 for k in shared for d in dims
                  if "none found" in (cand[k][f"Evidence ({d})"] or "").lower())
    total = len(shared) * len(dims)
    print(f"  {'evidence fields empty/none-found':40} "
          f"{nf_ref:>14} {nf_cand:>14}   of {total}")

    # --- publication type ---
    type_agree = sum(1 for k in shared if ref[k]["Type"] == cand[k]["Type"])
    print(f"\n--- publication type agreement: {type_agree}/{len(shared)} "
          f"({type_agree/len(shared):.0%}) ---")
    for k in shared:
        if ref[k]["Type"] != cand[k]["Type"]:
            print(f"  {ref[k]['Type']:22} -> {cand[k]['Type']:22} "
                  f"{ref[k]['Title'][:34]}")

    # --- biggest disagreements ---
    ranked = []
    for k in shared:
        total_diff = sum(
            abs((as_int(cand[k][f"Score ({d})"]) or 0)
                - (as_int(ref[k][f"Score ({d})"]) or 0))
            for d in dims
        )
        ranked.append((total_diff, k))
    ranked.sort(reverse=True)

    print(f"\n--- papers ranked by disagreement ---")
    for total_diff, k in ranked[:args.show]:
        if total_diff == 0:
            continue
        print(f"  [{total_diff}] {ref[k]['Title'][:62]}")
        for d in dims:
            a, b = ref[k][f"Score ({d})"], cand[k][f"Score ({d})"]
            if a != b:
                print(f"        {d:38} {a} -> {b}")
    if all(t == 0 for t, _ in ranked):
        print("  none -- every score matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
