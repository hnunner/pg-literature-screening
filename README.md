# Pandemic Guidelines — automated full-text screening

Screens papers against a review's five inclusion criteria using an LLM, writing
one auditable row per paper: a verdict on each criterion, the verbatim quote
behind it, and a decision derived from those verdicts by rule. Every judgement
carries the text it was based on, so a human can check it quickly, and genuinely
borderline papers come back `uncertain` rather than being forced.

**What this repository is.** The instrument used for the screening reported in
the paper, plus a record of how that screening went. It is not a way to
reproduce our run. That run is non-deterministic, and it needs local PDFs for
159 mostly paywalled papers we cannot redistribute. The screening output of
record is in the data deposit, [10.5281/zenodo.22232256](https://doi.org/10.5281/zenodo.22232256).

Two things you can do here. Read `pgscreen/criteria.py` and `pgscreen/rubric.py`
to see exactly what the model was asked and how a decision follows from its
answers. Or point the tool at a corpus of your own, for which the Quick start
below works as written.

---

## Quick start

```bash
python -m venv venv
venv\Scripts\activate            # Windows;  source venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env             # then add ANTHROPIC_API_KEY
```

Export a Zotero collection as CSV to `./data/articles-full-screen.csv` (see
`data/how-to-csv.md`), or build the same columns by hand. Then:

```bash
python full-screen.py --list-models    # what this run costs, per model
python full-screen.py --dry-run        # what would run, no API calls
python full-screen.py --limit 5        # try five first
python full-screen.py --batch          # the whole collection, at half price
python analyze.py results/articles-full-screen-results.csv
```

**Use `--batch` for a full corpus.** It goes through the Batches API at half the
token cost, trading latency: results arrive when the batch completes, usually
inside an hour against a 24 hour ceiling. It prints a batch ID, so an interrupted
collection resumes with `--resume-batch <id>`. For `--limit` spot checks the
default streaming path is more useful.

Runs are resumable either way. Papers already screened are skipped, `--fresh`
starts over, and transient API errors are written as failed rows and picked up on
a rerun rather than lost. Every run prices itself and asks before spending.

---

## Which model

**Use `claude-sonnet-5`.** Measured, not assumed.

Over the same 20 papers, Sonnet returned 19 include and 1 exclude, the exclude
being the agreed bibliometric-review case. Haiku 4.5 returned 17 include and 3
exclude, all three false negatives, at roughly a third of the cost. Haiku fails
papers on criterion 2 for "not itself developing or applying a model", which
excludes exactly the reviews, editorials, and perspectives that criterion 5
explicitly admits. Rubric `2026-07-28.6` hardened the wording against this, but
the error ran in the costly direction, so Haiku is not recommended. Opus 5
agreed with Sonnet at 90% exact on an earlier rubric at about 2.2 times the cost,
which is not worth the difference here.

Cost is driven by PDF pages at roughly 3,950 input tokens each, calibrated
against a real invoice rather than estimated.

---

## The instrument

`pgscreen/criteria.py` holds the five protocol criteria verbatim.
`pgscreen/rubric.py` holds the operational guidance, the quality-appraisal
dimensions, and the JSON schema. Three design decisions matter:

1. **One field per criterion.** The original prompt scored two: criteria 4 and 5
   were concatenated into a single "Modeling Relevance" value and criteria 1 and
   2 were absent. Collapsing distinct requirements into one score destroys
   discriminatory power, since a paper satisfying one half and failing the other
   lands mid-scale instead of failing.
2. **Evidence before judgement.** Each criterion asks for a verbatim quote and a
   one-line rationale *before* the verdict. Models generate JSON fields in schema
   order, so this conditions the judgement on located text. It also caught a PDF
   that was a BMJ correction notice rather than the article.
3. **The decision is computed, not asked for.** `rubric.decide()` applies the rule
   to the five verdicts. Asked for the decision directly, the model contradicted
   its own scores in 11 of 67 cases, always permissively. Its call is still
   recorded as `Model Decision` with a `Decision Mismatch` flag, and where the two
   differ a human should look.

Quality dimensions (Evidence Base, Breadth, Uncertainty & Bias, Transparency) are
scored 0 to 2 and deliberately do **not** affect inclusion.

---

## Files

|                        |                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------- |
| `full-screen.py`       | Main entry point: full-text screening.                                            |
| `analyze.py`           | Summarise a run: decisions, criterion verdicts, rows needing review.              |
| `compare_runs.py`      | Compare two runs over the same papers, after a model or rubric change.            |
| `make_stress_set.py`   | Pick the papers most likely to be excluded, to test the rubric where it can fail. |
| `pgscreen/criteria.py` | The five criteria, verbatim from the protocol.                                    |
| `pgscreen/rubric.py`   | Guidance, quality dimensions, schema, decision rule.                              |
| `pgscreen/providers.py`| Anthropic (native PDF) and OpenAI-compatible backends.                            |
| `pgscreen/pipeline.py` | Concurrency, resume, CSV output.                                                  |
| `pgscreen/models.py`   | Model registry, pricing, cost estimation.                                         |

`--backend openai --base-url ...` works with OpenAI, OpenRouter, vLLM, Ollama, or
a university gateway. That path extracts PDF text locally rather than sending the
document, so the model sees no tables, figures, or layout. Treat a backend switch
as a new run, not a continuation.

---

## The run we reported

**159 papers, rubric `2026-07-28.6`: 135 include (85%), 24 exclude (15%), 0 failed.**

Discrimination concentrated where the rubric says it should:

| publication type    |  n | excluded |
| ------------------- | -: | -------: |
| Review article      | 61 |       7% |
| Perspective/Opinion | 34 |       9% |
| Systematic review   | 24 |      12% |
| **Research article**| **21** | **48%** |

A sevenfold difference between research articles and reviews, and all ten
research-article exclusions fell under criterion 5, the deletion-test clause doing
the job it was written for. Criterion 5 accounts for 21 of the 24 exclusions,
matching how the human abstract round used it (83 of 116).

**The high include rate appears to be correct.** Composition explains most of it:
this corpus is the Rayyan "Maybe" set, already filtered against the same five
criteria (277 to 160), and 111 of 160 read as reviews or perspectives, which
criterion 5 admits. The discriminating clause still fires. `make_stress_set.py`
ranks the corpus by how much each paper reads like a single study, and on the
hardest 6 both Sonnet and Opus excluded the same research article on criterion 5,
agreeing on 5 of 5 decisions and 25 of 25 verdicts, so model choice is not
confounding it. Re-run that script after any rubric change, since a random sample
here mostly asks questions the instrument gets right by construction.

### Human verification

| reviewed                          |               n | confirmed |
| --------------------------------- | --------------: | --------: |
| Every exclusion, whole population  |              24 |    **24** |
| Random sample of inclusions        |       60 of 135 |    **60** |
| **Total**                          | **84 of 159 (53%)** | **84 (100%)** |

The two halves are not equally strong evidence. Exclusion precision is
established outright, since all 24 were reviewed with no sampling uncertainty at
all, and none was wrongly excluded. Inclusion is a sample: zero errors in 60
draws from a population of 135 puts the one-sided 95% bound at most 5 wrongly
included papers, about 3.7%, with the finite-population correction mattering
because 44% of the group was inspected. The costly direction in screening is
wrongly excluding a relevant paper, and that side is verified exhaustively.

### Three things checked by hand

1. **One row was screened by Haiku 4.5**, because Sonnet 5 and Opus 5 both refused
   it, a safety-classifier false positive on a clean Frontiers in Physiology
   paper. Haiku returned `include` and a human confirmed it. That row came from a
   different model than the other 158.
2. **`unclear` never fired**, 0 of 795 criterion assessments. Either full text
   settles every question, or the model resolves ambiguity instead of flagging it.
   Real hesitation does show up in `Screening Notes`, so there is no automatic
   borderline queue and the notes serve instead.
3. **27 of 39 screening notes are noise** ("the PDF matches the bibliographic
   record") despite the schema asking for an empty string when there is nothing to
   report. The other 12 are valuable: a workshop call-for-papers mis-filed as an
   article, a meeting abstract, a paper whose PDF header claims "Research Article"
   but whose content is not one.

### Why validation took this shape

No pre-built control set was possible. Earlier screening collections each
encoded a superseded round, and the only other human ground truth, the Rayyan
title and abstract export, has PDFs for 1 of its 117 excluded papers, so it
cannot be replayed at full text. It is not distributed here. Hence the stratified
review of the real run, which gives agreement in both directions and doubles as
the quality-control pass the review needed anyway.

An earlier title and abstract validation arm was built and removed: it measured
93% sensitivity over 271 records, but its specificity was an artifact of
abstract-mode instructions reading silence as *unclear*, correct for full text
and wrong for abstracts. Its lasting value, the mapping from Rayyan's "Criterion
N" exclusions to the protocol text, survives in `pgscreen/criteria.py`.

---

## How the corpus of PDFs was assembled

A record of what we did, not a procedure to follow. Anyone screening a different
corpus supplies their own PDFs and needs none of this.

Zotero's "Find Available PDF" was the tool that worked, because it reaches
paywalled content through institutional subscriptions where Unpaywall cannot. It
did not fire on the collection as it stood: all 160 items already carried an
attachment *record* pointing at a file that had never been downloaded, with
`storageHash` NULL on every one, so Zotero concluded there was nothing to fetch.

After backing up `zotero.sqlite` we trashed those phantom records with a
throwaway script, 140 of 160, keeping the 20 that had a real file. Running Find
Available PDF on the university network then took the collection from 20
resolvable PDFs to 111, access being granted by IP, and repeated passes plus
manual downloading closed the rest. The collection sat in a shared project group
library, so the trashing propagated to collaborators.

Two findings cost enough time to record. **Scripted open-access fetching did not
work for this corpus:** a DOI to Unpaywall to download tool retrieved 1 of 49,
since many hosts (NCBI/PMC, MDPI, DOAJ, ScienceDirect) block scripted retrieval
as policy and most of these articles are not in the PMC Open Access Subset even
where Unpaywall reports them as open. **A browser on the university network was
the route that worked:** opening the article and using the Zotero Connector
carries the session.

A semicolon inside a paper's title also broke attachment-path parsing, since
Zotero separates multiple attachments with `;`. `pipeline.first_attachment()` now
tries the whole string before splitting.

---

## License

MIT, see [LICENSE](LICENSE).
