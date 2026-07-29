# Pandemic Guidelines — automated full-text screening

Screens papers against the review's five inclusion criteria using an LLM, and writes one auditable row per paper: a verdict on each criterion, the verbatim
quote behind it, and a decision derived from those verdicts by rule.

Every judgement carries the text it was based on so a human can check it quickly, and genuinely borderline papers come back `uncertain` rather than being forced.

---

## Quick start

```bash
python -m venv venv
venv\Scripts\activate            # Windows;  source venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env             # then add ANTHROPIC_API_KEY
```

Export the collection from Zotero as CSV to `./data/articles-full-screen.csv`
(see `data/how-to-csv.md`), then:

```bash
python full-screen.py --list-models    # what this run costs, per model
python full-screen.py --dry-run        # what would run, no API calls
python full-screen.py --limit 5        # try five first
python full-screen.py --batch          # the whole collection, at half price
python analyze.py results/articles-full-screen-results.csv
```

**Use `--batch` for the full corpus.** It submits everything through the Batches API at half the token cost — ~$13.70 instead of ~$27.40 at list price, ~$9.20 on
Sonnet's introductory rate. The trade is latency: results arrive when the batch completes (usually inside an hour, 24h ceiling) rather than streaming in. It
prints a batch ID, so an interrupted collection resumes with`--resume-batch <id>`. For `--limit` spot checks, the default streaming path is
more useful.

Runs are resumable either way: papers already screened successfully are skipped, so an interrupted run continues rather than restarting. `--fresh` starts over.
Expect the odd transient API error across 159 papers — those are written as failed rows and picked up on a rerun, not lost.

---

## Which model

**Use `claude-sonnet-5`.** This is measured, not assumed.

On the current five-criterion rubric, over the same 20 papers:

|                  | Sonnet 5                                             | Haiku 4.5                          |
| ---------------- | ---------------------------------------------------- | ---------------------------------- |
| Decisions        | 19 include, 1 exclude                                | 17 include, 3 exclude              |
| Correct?         | the 1 exclude is the agreed bibliometric-review case | all 3 excludes are false negatives |
| Cost, 160 papers | ~$17.50 | ~$6.00                                     |                                    |

Haiku fails papers on Criterion 2 for "not itself developing or applying a model" — which excludes exactly the reviews, editorials and perspectives that
Criterion 5 explicitly admits. The rubric wording was hardened against this in `2026-07-28.6`, but Haiku's error was in the costly direction (dropping papers
that belong), so it is not recommended.

Opus 5 was compared earlier and agreed with Sonnet at 90% exact on the previous rubric, at roughly 2.2× the cost. It is not worth the difference here.

Cost is driven by PDF pages at **~3,950 input tokens each** — measured against a real invoice, not estimated. `--list-models` prices any run before it starts,
and every run asks for confirmation before spending.

---

## The instrument

`pgscreen/criteria.py` holds the five protocol criteria verbatim. `pgscreen/rubric.py` holds the operational guidance for applying them, the quality-appraisal
dimensions, and the JSON schema.

Three design decisions matter:

1. **One field per criterion.** The protocol has five criteria. The original
   prompt scored *two*: criteria 4 and 5 were concatenated into a single
   "Modeling Relevance" value and criteria 1 and 2 were absent entirely.
   Collapsing distinct requirements into one score is what destroys
   discriminatory power — a paper satisfying one half and failing the other
   lands mid-scale instead of failing.
2. **Evidence before judgement.** Each criterion asks for a verbatim quote and
   a one-line rationale *before* the verdict. Models generate JSON fields in
   schema order, so this conditions the judgement on located text. In practice
   this also caught a PDF that was a BMJ correction notice rather than the
   article.
3. **The decision is computed, not asked for.** `rubric.decide()` applies the
   rule to the five verdicts. When the model was asked for the decision
   directly it contradicted its own scores in 11 of 67 cases, always
   permissively. The model's own call is still recorded as `Model Decision`
   with a `Decision Mismatch` flag — where the two differ, a human should look.

Quality dimensions (Evidence Base, Breadth, Uncertainty & Bias, Transparency) are scored 0–2 and deliberately do **not** affect inclusion.

---

## Files

|                                               |                                                                                   |
| --------------------------------------------- | --------------------------------------------------------------------------------- |
| `full-screen.py`                            | Main entry point: full-text screening.                                            |
| `analyze.py`                                | Summarise a run — decisions, criterion verdicts, rows needing review.            |
| `compare_runs.py`                           | Compare two runs over the same papers (model or rubric changes).                  |
| `make_stress_set.py`                        | Pick the papers most likely to be excluded, to test the rubric where it can fail. |
| `tools/zotero-clear-phantom-attachments.js` | Unblock Zotero's "Find Available PDF" (kept as a record of what was done).        |
| `pgscreen/criteria.py`                      | The five criteria, verbatim from the protocol.                                    |
| `pgscreen/rubric.py`                        | Guidance, quality dimensions, schema, decision rule.                              |
| `pgscreen/providers.py`                     | Anthropic (native PDF) and OpenAI-compatible backends.                            |
| `pgscreen/pipeline.py`                      | Concurrency, resume, CSV output.                                                  |
| `pgscreen/models.py`                        | Model registry, pricing, cost estimation.                                         |

### Another provider

`--backend openai --base-url ...` works with OpenAI, OpenRouter, vLLM, Ollama, or a university gateway. That path extracts PDF text locally rather than sending
the document, so the model sees no tables, figures or layout — treat a backend switch as a new run, not a continuation.

---

## Getting the PDFs — done

**All 159 papers have a resolvable PDF.** Kept here because the same trap will reappear if the collection is ever repopulated.

Zotero's "Find Available PDF" is the right tool — it reaches paywalled content
through your institutional subscriptions, which Unpaywall cannot — but it will
not fire on this collection as-is. All 160 items already have an attachment
*record* pointing at a file that was never downloaded (`storageHash` is NULL for
all of them), so Zotero concludes there is nothing to fetch: a multi-item
selection reports "No files found" and the menu entry disappears on single
items.

To unblock it:

1. Back up `%USERPROFILE%\Zotero\zotero.sqlite`.
2. Run `tools/zotero-clear-phantom-attachments.js` in Zotero
   (Tools → Developer → Run JavaScript). Step 1 audits and should report
   **160 items, 20 attachments with a file, 140 phantom**. Step 2 moves the 140
   empty records to the trash.
3. **Connect to the university network or VPN**, then select the collection →
   right-click → Find Available PDF. Access is decided by your IP, so doing this
   off-network gets open access only and wastes the run.
4. Re-export the collection to `data/articles-full-screen.csv` — the
   File Attachments paths will have changed.

Note that `full screen` is in the **group** library `infoXpandUZL`, so trashing
those records syncs to collaborators.

That took the collection from 20 to 111 in one pass; repeated passes and manual
downloading closed the rest.

Two things worth recording, because both cost time:

- **Scripted open-access fetching does not work for this corpus.** A DOI →
  Unpaywall → download tool retrieved 1 of 49. Some papers are not open access
  at all, and the hosts holding the rest (NCBI/PMC, MDPI, DOAJ, ScienceDirect)
  block scripted retrieval as policy — including through NCBI's own sanctioned
  OA Web Service, since most of these articles are not in the PMC Open Access
  Subset even where Unpaywall reports them as open. The tool was deleted rather
  than left as a trap.
- **The browser on the university network is the route that works.** Open the
  article and use the Zotero Connector, which carries your session.

A semicolon inside a paper's title also broke attachment-path parsing (Zotero
separates multiple attachments with `;`). `pipeline.first_attachment()` now
tries the whole string before splitting.

### Result of the full run (159 papers, rubric 2026-07-28.6)

**135 include (85%), 24 exclude (15%), 0 failed.**

The discrimination is concentrated exactly where the rubric says it should be:

| publication type           |            n |      excluded |
| -------------------------- | -----------: | ------------: |
| Review article             |           61 |            7% |
| Perspective/Opinion        |           34 |            9% |
| Systematic review          |           24 |           12% |
| **Research article** | **21** | **48%** |

A seven-fold difference between research articles and reviews, and **all ten
research-article exclusions were criterion 5** — the deletion-test clause doing
precisely the job it was written for. Criterion 5 accounts for 21 of the 24
exclusions overall, matching how the human abstract round used it (83 of 116
exclusions).

Earlier samples returning almost nothing but includes were a sampling artifact:
both happened to contain zero research articles.

### The include rate is high, and that appears to be correct

Screening returns mostly includes. That was the original complaint about the
previous instrument, so it was tested directly rather than argued about.

**Composition explains most of it.** This corpus is the Rayyan "Maybe" set,
already filtered against these same five criteria (277 → 160). 111 of 160 read
as reviews or perspectives — which criterion 5 explicitly admits — and only 9
carry single-study wording. A low exclusion rate is what agreement looks like
here.

**The discriminating clause does fire.** `make_stress_set.py` ranks the corpus
by how much each paper reads like a single study; the top 6 were screened on
both Sonnet and Opus. Both excluded the one research article on criterion 5,
both citing the deletion test by name and identifying the same failure mode
(*"broader framing is confined to a related-work critique motivating the
authors' own design"*).

**Model choice is not confounding it.** On that same adversarial set, Sonnet and
Opus agreed on **5/5 decisions and 25/25 criterion verdicts**, at 1.8× the cost
for Opus. A cheaper model is not reading the rubric more liberally — and the one
failure mode observed in Haiku was over-*exclusion* (rejecting papers about
modelling on criterion 2), never over-inclusion.

Re-run `make_stress_set.py` after any rubric change: a random sample of this
corpus mostly asks questions the instrument gets right by construction.

### Human verification of the run

A stratified review was carried out on the completed run:

| reviewed                                                      |                         n |           confirmed |
| ------------------------------------------------------------- | ------------------------: | ------------------: |
| **Every exclusion** (complete population, not a sample) |                        24 |        **24** |
| Random sample of inclusions                                   |                 60 of 135 |        **60** |
| **Total**                                               | **84 of 159 (53%)** | **84 (100%)** |

The two halves are not equally strong evidence, and a methods section should say
so:

- **Exclusion precision is established outright.** All 24 exclusions were
  reviewed — the entire population, so there is no sampling uncertainty at all.
  The instrument did not wrongly exclude a single paper.
- **Inclusion is a sample, but a substantial one.** 60 of 135 checked, all
  confirmed. With zero errors in 60 draws from a population of 135, the
  one-sided 95% bound is **at most 5 wrongly-included papers (~3.7%)** — the
  finite-population correction matters here, since 44% of the group was
  inspected.

The costly direction in screening is wrongly *excluding* a relevant paper, and
that side is verified exhaustively.

Suggested wording: *"All 24 automated exclusions were independently verified by a
human reviewer and all were confirmed. A random sample of 60 of 135 automated
inclusions (44%) was verified, all confirmed. Agreement was 84/84 (100%) across
53% of the screened corpus."*

### Three things checked by hand

1. **One row was screened by Haiku 4.5** (`Aerosol Transport Modeling…`), because
   both Sonnet 5 and Opus 5 refused it — a safety-classifier false positive on a
   clean Frontiers in Physiology paper. Haiku returned `include`; a human
   confirmed it. Worth recording in the methods, since that row was produced by
   a different model from the other 158.
2. **`unclear` never fired** — 0 of 795 criterion assessments. Either full text
   genuinely settles every question, or the model resolves ambiguity instead of
   flagging it. It does record real hesitation in `Screening Notes` ("criterion
   5 is a closer call than the others"), so the hedging goes there rather than
   into the verdict. Consequence: there is no automatic borderline queue — use
   the notes instead.
3. **27 of 39 screening notes are noise** ("the PDF matches the bibliographic
   record") despite the schema asking for an empty string when there is nothing
   to report. The other 12 are genuinely valuable — a workshop call-for-papers
   mis-filed as an article, a meeting abstract, a paper whose PDF header says
   "Research Article" but whose content is not one.

### Why validation took the shape it did

No pre-built control set was possible, for structural reasons worth recording:

- Every Zotero collection carrying prior screening decisions (`1.`, `2.`, `3.x`,
  `4.`, `5.`) sits under `_deprecated` and encodes a superseded round. Controls
  built from them were discarded after the fact.
- The only other human ground truth is `rayyan-screened-export.csv`, which is
  *title/abstract* stage. Its 117 excluded papers have PDFs for 1 of 117, so it
  cannot be replayed at full text.

Hence the stratified review of the real run, above: it produces agreement in
both directions, concentrates reading effort on the informative cases, and
doubles as the quality-control pass the review needs anyway.

An earlier title/abstract validation arm was built and removed. It measured 93%
sensitivity over 271 records, but its specificity figure was an artifact of
abstract-mode instructions that deliberately read silence as *unclear* — correct
for full text, wrong for abstracts. Its lasting value, the mapping from Rayyan's
"Criterion N" exclusions to the protocol text, is preserved in
`pgscreen/criteria.py`.
