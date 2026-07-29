#!/usr/bin/env python3
"""
make_stress_set.py -- pick the papers most likely to be excluded, so the
instrument is tested where it can actually fail.

A random sample of this corpus is a weak test. Two thirds of it is reviews and
perspectives, which criterion 5 explicitly admits, so a random draw mostly
asks questions the instrument gets right by construction. The rubric's
strictest clause -- a research article reporting original model results starts
from 'not met' on criterion 5 -- only fires on single-study papers, and those
are rare here.

This ranks the corpus by how much it looks like a single-study paper and how
little it looks like a review, using the Rayyan abstracts, and writes the top N
to a CSV the pipeline can screen.

  python make_stress_set.py --limit 6 --out data/stress.csv
  python full-screen.py --input data/stress.csv --output results/stress.csv
  python analyze.py results/stress.csv

Read the result as a directional check, not a measurement: these are the papers
most likely to be excludes, but nobody has labelled them, so you are judging
whether the verdicts and their quotes are defensible.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# Wording that suggests the paper reports one study of its own.
SINGLE_STUDY = re.compile(
    r"\b(we (develop|present|propose|construct|fit|calibrate|implement|apply)"
    r"|this (study|paper|article) (develops|presents|proposes|introduces|applies)"
    r"|our model|the proposed model|a novel|we estimate|we simulate"
    r"|case study|we compare .{0,30}scenarios)\b", re.I)

# Wording that suggests the paper stands back from any single model.
REVIEW_LIKE = re.compile(
    r"\b(review|perspective|editorial|commentary|viewpoint|opinion|lessons"
    r"|challenges|future directions|research agenda|overview|scoping"
    r"|systematic search|we synthesi[sz]e|state of the art)\b", re.I)


def rayyan_abstracts(path):
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            doi = re.sub(r"^https?://(dx\.)?doi\.org/", "",
                         (row.get("doi") or "").strip().lower())
            if doi:
                out[doi] = (row.get("title") or "") + "\n" + (row.get("abstract") or "")
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", default="./data/articles-full-screen.csv")
    ap.add_argument("--rayyan", default="./rayyan-screened-export.csv")
    ap.add_argument("--out", default="./data/stress.csv")
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    for path in (args.input, args.rayyan):
        if not Path(path).is_file():
            sys.exit(f"No such file: {path}")

    abstracts = rayyan_abstracts(args.rayyan)
    with open(args.input, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    scored = []
    for row in rows:
        doi = (row.get("DOI") or "").strip().lower()
        text = abstracts.get(doi) or (row.get("Title") or "")
        single = len(SINGLE_STUDY.findall(text))
        reviewish = len(REVIEW_LIKE.findall(text))
        # Most single-study-like, least review-like, first.
        scored.append((single - reviewish, single, reviewish, row))
    scored.sort(key=lambda t: (-t[0], -t[1]))

    picked = [r for _s, _a, _b, r in scored[:args.limit]]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(picked)

    print(f"Ranked {len(rows)} papers by how much they look like single-study "
          f"work.\nTop {len(picked)} written to {out}:\n")
    for score, single, reviewish, row in scored[:args.limit]:
        print(f"  [single {single} / review {reviewish}]  {row['Title'][:62]}")
    print(f"\nFor contrast, the least single-study-like in the corpus:")
    for score, single, reviewish, row in scored[-3:]:
        print(f"  [single {single} / review {reviewish}]  {row['Title'][:62]}")
    print(f"\nNext:\n"
          f"  python full-screen.py --input {out} --output results/stress.csv\n"
          f"  python analyze.py results/stress.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
