"""
The screening instrument: category definitions, scoring anchors, and the JSON
schema the model must fill in.

This module is deliberately separate from the pipeline. It is the part that gets
revised as the review protocol is refined, and revising it should never require
touching provider or CSV code.

Three ideas drive the design:

1.  One field per criterion. The protocol has five inclusion criteria; an
    earlier version of this instrument scored two, having concatenated criteria
    4 and 5 into a single value and omitted 1 and 2 entirely. Collapsing
    distinct requirements into one score is what destroys discriminatory power:
    a paper that satisfies one half and fails the other lands in the middle
    instead of failing. Each criterion is now assessed on its own, so the
    instrument's output lines up with how exclusions were actually recorded.
2.  Evidence before judgement. Every criterion and every scored dimension asks
    for a verbatim quote and a one-line rationale *before* the verdict. Models
    generate JSON fields in schema order, so this conditions the judgement on
    located text rather than on a general impression.
3.  Requirements are met or not met, quality is scored. The protocol states each
    criterion as a "must", so they take met / not met / unclear rather than a
    scale. Only the four appraisal dimensions are scored 0-2, and those do not
    affect inclusion.
"""

from . import criteria

RUBRIC_VERSION = "2026-07-28.6"

# Per-criterion guidance. The protocol wording lives in criteria.py; this is the
# operational detail needed to apply it consistently, gathered from watching
# where models actually go wrong on this corpus.
CRITERION_NOTES = {
    1: "Nearly every paper reaching full-text screening passes this. Mark it not "
       "met only for a genuine scope failure -- a paper about chronic disease, "
       "non-communicable conditions, or health systems with no infectious "
       "disease content.",
    2: "'Focus on mathematical models' means the paper is *about* modeling. It "
       "does NOT mean the paper must contain, develop, or run a model of its "
       "own. A review, editorial, perspective or commentary whose subject is "
       "infectious disease modeling meets this criterion fully while presenting "
       "no model at all -- criterion 5 explicitly admits exactly those formats, "
       "so requiring an original model here would contradict it. This is the "
       "commonest error on this criterion: do not mark a paper 'not met' "
       "because it 'does not itself develop or apply a model'.\n"
       "    What fails instead is a paper where modeling is not the subject: a "
       "descriptive epidemiological study, a survey, a clinical study, or a "
       "policy analysis that cites model outputs as background evidence. "
       "Statistical, Bayesian and machine-learning models all count, so do not "
       "read 'mathematical' narrowly -- but reporting fitted trends is not the "
       "same as modeling disease dynamics.",
    3: "Score the body, not the framing. Papers routinely promise policy "
       "relevance in the abstract and deliver none. An applied forecasting study "
       "that never discusses how the forecast was or should be used does not "
       "meet this criterion, however topical its subject.",
    4: "A boilerplate limitations paragraph -- 'our model assumes homogeneous "
       "mixing' -- is not a critical discussion of the role and limitations of "
       "modeling. Look for engagement with what modeling can and cannot do, not "
       "a required disclosure.",
    5: "Apply the deletion test: if this paper's own model and results were "
       "removed, would anything remain that is a claim about modeling as a "
       "practice? Method-selection rationale is the commonest false positive -- "
       "'mean-field models miss clustering, so we use an agent-based model' "
       "justifies the study's own design and does not meet this criterion, "
       "however critically argued. Bibliometric and scoping reviews that map who "
       "publishes what, without examining how modeling is done, also fail here. "
       "A research article reporting original model results starts from 'not "
       "met' and has to earn its way out.",
}

PAPER_TYPES = [
    "Research article", "Review article", "Systematic review", "Meta-analysis",
    "Perspective/Opinion", "Editorial", "Commentary", "Letter",
    "Conference paper", "Technical report", "Policy paper",
    "Book chapter", "Book", "Thesis", "Preprint", "Other",
]

SCOPE_FIELDS = [
    ("disease", "disease or pathogen"),
    ("modeling_approach", "modeling approach or method family"),
    ("social_context", "social, cultural, or institutional context"),
    ("population", "population or subgroup"),
    ("geography", "country, region, or setting"),
    ("time_period", "time period or epidemic wave"),
    ("data_source", "named data source, registry, or surveillance system"),
]

# Quality appraisal. These describe how well a paper is made and deliberately do
# NOT feed the inclusion decision -- a poorly evidenced paper that meets all five
# criteria is still an include.
# Each entry: (key, human label, the question, the three anchors).
DIMENSIONS = [
    (
        "evidence_base",
        "Evidence Base",
        "Are the paper's claims anchored in cited evidence, or asserted?",
        {
            2: "Claims are consistently supported by citations to primary studies, "
               "reviews, or seminal work. Where the authors advance a contested "
               "position, they engage with the literature on both sides.",
            1: "Partly referenced. Key claims are cited but others rest on assertion or "
               "authority; or the citation set is thin, one-sided, or heavily "
               "self-referential.",
            0: "Substantially unreferenced assertion. Few or no citations supporting the "
               "central claims.",
        },
    ),
    (
        "breadth_of_discussion",
        "Breadth of Discussion",
        "Does the paper take a holistic view of modeling challenges, or treat one "
        "narrow aspect?",
        {
            2: "Spans several distinct dimensions -- e.g. technical, data, "
               "institutional, communication, ethical -- and relates them to one "
               "another rather than listing them.",
            1: "Covers more than one aspect but stays within one register (e.g. several "
               "technical issues), or touches broader themes only in passing.",
            0: "Confined to a single narrow issue or a single aspect of modeling.",
        },
    ),
    (
        "uncertainty_and_bias",
        "Acknowledgment of Uncertainty & Bias",
        "Does the paper engage seriously with uncertainty, limitations, and its own "
        "position, or advocate one-sidedly?",
        {
            2: "Substantive treatment of uncertainty, limitations, or bias, with a "
               "balanced view that credits competing positions or acknowledges where "
               "the authors' own stance may be wrong.",
            1: "Uncertainty or limitations are acknowledged but handled briefly or "
               "formulaically; the paper leans clearly toward one position without "
               "seriously engaging alternatives.",
            0: "Little or no acknowledgment; sustained one-sided advocacy.",
        },
    ),
    (
        "transparency",
        "Transparency",
        "Can a reader reconstruct how the authors reached their conclusions? Apply "
        "the standard appropriate to the paper type.",
        {
            2: "Fully transparent for its type. Review: search strategy, selection, and "
               "synthesis described. Research article: methods, data, and assumptions "
               "sufficient to replicate; code or data availability where relevant. "
               "Opinion/editorial: authors' background, role, or competing interests "
               "disclosed, and the basis for their claims made clear.",
            1: "Partially transparent. Some of the above present, material gaps remain "
               "(e.g. a review that names databases but not inclusion criteria).",
            0: "Opaque. Conclusions cannot be traced to a described process, and no "
               "relevant disclosure is offered.",
        },
    ),
]

_TYPE_GUIDANCE = """\
Classify by what the paper *does*, not by where it appeared or what it is
labelled. Apply in order and take the first that fits:

- Systematic review / Meta-analysis: states an explicit, reproducible search and
  selection procedure. Meta-analysis additionally pools results statistically.
- Review article: surveys a body of literature without a formal search protocol.
- Research article: presents original analysis, data, or model results.
- Perspective/Opinion: advances the authors' argued position, typically without
  new data. Includes "viewpoint" and "essay" formats.
- Editorial: written by journal editors or invited to frame an issue or section.
- Commentary: responds to a specific paper, event, or policy.
- Letter: short correspondence.
- Conference paper, Technical report, Policy paper, Book chapter, Book, Thesis,
  Preprint: use when the venue determines the form.
- Other: only when nothing above fits. State what it is in the evidence field.

A journal's own section heading ("Perspective", "Review") is strong evidence --
prefer it when it does not contradict the content."""

_SCOPE_GUIDANCE = """\
These fields record how *narrow* the paper's claims are. They are not a topic
index -- do not list everything mentioned.

The test: if the paper's central argument would no longer hold once you removed
this disease / method / population / setting, it is specific. If the argument is
general and the item merely illustrates it, it is not.

Write "NA" when the paper's discussion is general with respect to that
dimension. A review of modeling for pandemic preparedness that draws examples
from influenza, COVID-19, and Ebola is NA for disease -- the argument does not
depend on any one of them. A paper whose claims hold only for cholera in
Haiti is specific for both disease and geography.

Prefer "NA" when uncertain. Over-filling these fields is the more damaging
error, because it makes a general paper look narrow."""

_CALIBRATION = """\
Calibration notes -- these correct the failure modes seen most often:

- Do not reward topicality. A paper being about COVID-19, pandemics, or
  preparedness says nothing about whether it meets the criteria.
- Do not reward the abstract's framing. Papers routinely promise policy
  relevance in the abstract and deliver none in the body. Score the body.
- A score of 1 is a substantive finding, not a hedge. If you cannot state what
  is present *and* what is missing, the paper is a 0 or a 2, not a 1.
- The five criteria are independent requirements. A paper routinely meets some
  and fails others; that is the normal case, not a sign you have misread it. Do
  not let a strong showing on one criterion soften your verdict on another.
- Criteria 4 and 5 are the pair most often confused. Criterion 4 asks whether
  the paper discusses limitations and challenges at all. Criterion 5 asks
  whether it is *about* something wider than its own model. A single-model paper
  with a thoughtful limitations section meets 4 and fails 5.
- If you cannot locate supporting text for a score of 1 or 2, the score is 0.
  Absence of evidence in the document is evidence of absence for these purposes.
- The comment fields are for the screener to audit your reasoning. Write
  compressed noun phrases, not sentences: "policy framing in abstract only;
  body is parameter estimation"."""


def _dimension_block(key, label, question, anchors):
    lines = [f"### {label}", "", question, ""]
    for level in (2, 1, 0):
        lines.append(f"- **{level}** - {anchors[level]}")
    return "\n".join(lines)


def _criterion_block(number):
    c = criteria.CRITERIA[number]
    return (
        f"### Criterion {number} -- {c['short']}\n\n"
        f"{c['requirement']}\n\n"
        f"*Excluded:* {c['exclusion']}\n\n"
        f"How to apply it: {CRITERION_NOTES[number]}"
    )


def build_system():
    """The instrument itself.

    Identical for every paper, so it is sent as a cacheable prefix rather than
    rebuilt per request.
    """
    criterion_blocks = "\n\n".join(
        _criterion_block(n) for n in sorted(criteria.CRITERIA)
    )
    dimensions = "\n\n".join(
        _dimension_block(*d) for d in DIMENSIONS
    )
    scope_list = "\n".join(
        f"- `scope_{key}`: {desc}" for key, desc in SCOPE_FIELDS
    )
    return f"""\
You are screening papers for a systematic review on the role of mathematical
modeling of infectious diseases in public health decision-making.

For each paper you are given the full text. Read it before answering. Base every
judgement on what the attached document actually says -- not on the title, not
on the journal, and not on what you may know about the paper from elsewhere.

## 1. Inclusion criteria

The review has five criteria. Each is a requirement, so assess each one
separately as **met**, **not met**, or **unclear**. A paper is included only if
all five are met -- but do not work backwards from a decision you have already
formed: judge each criterion on its own evidence and let the decision follow.

Use **unclear** only when the document genuinely does not settle the question --
a truncated or unreadable text, or a criterion the paper never addresses either
way. It is not a hedge for a judgement you would rather not make.

For each criterion, in this order: quote the passage that most directly bears on
it, state your reasoning in one line, then give the verdict.

{criterion_blocks}

## 2. Publication type

{_TYPE_GUIDANCE}

## 3. Scope fields

{scope_list}

{_SCOPE_GUIDANCE}

## 4. Quality appraisal

These four dimensions describe how well the paper is made. They do **not** affect
inclusion -- a poorly evidenced paper that meets all five criteria is still an
include, and a beautifully made one that fails a criterion is still excluded.

For each dimension below, in this order: quote the passage that most directly
supports your judgement, state your reasoning in one line, then score.

Quotes must be verbatim from the attached document, at most 40 words, and
sufficient on their own to justify the score. If no such passage exists, write
"none found" -- and score accordingly.

{dimensions}

## 5. Calibration

{_CALIBRATION}

## 6. Decision

- `include`   - all five criteria met.
- `exclude`   - any criterion not met.
- `uncertain` - no criterion failed, but one or more could not be settled.

Derive the decision from the verdicts you have already given; do not re-litigate
them here. If applying the rule produces a decision that feels wrong, keep the
rule and say why in `decision_rationale` -- that disagreement is a signal about
the instrument, and suppressing it hides the problem.

Return the structured object. Every field is required.
"""


def build_user_text(paper):
    """The per-paper half: bibliographic context for the attached PDF."""
    return f"""\
Screen the attached paper.

Bibliographic record (context only; the PDF is authoritative):
  Title:   {paper.get('title') or 'unknown'}
  Authors: {paper.get('author') or 'unknown'}
  Year:    {paper.get('year') or 'unknown'}
  Journal: {paper.get('journal') or 'unknown'}
  DOI:     {paper.get('doi') or 'unknown'}

If the attached PDF is clearly a different paper than the record above, say so
in `screening_notes` and screen the PDF you were given.
"""


def decide(verdicts):
    """The inclusion rule, as a function of the five criterion verdicts.

    Each criterion is stated in the protocol as a requirement, so a paper is
    included only when all five are met. Kept here so the prompt, the pipeline
    and any after-the-fact backfill cannot drift apart -- all three read this.

    `verdicts` maps criterion number -> 'met' | 'not met' | 'unclear'.
    Returns (decision, rationale).
    """
    missing = [n for n in criteria.CRITERIA if n not in verdicts]
    if missing:
        return "uncertain", (
            f"No verdict recorded for criterion {', '.join(map(str, missing))}."
        )

    failed = [n for n, v in sorted(verdicts.items()) if v == "not met"]
    if failed:
        names = ", ".join(f"{n} ({criteria.CRITERIA[n]['short']})" for n in failed)
        return "exclude", f"Fails criterion {names}."

    unclear = [n for n, v in sorted(verdicts.items()) if v == "unclear"]
    if unclear:
        names = ", ".join(f"{n} ({criteria.CRITERIA[n]['short']})" for n in unclear)
        return "uncertain", f"Criterion {names} could not be settled from the text."

    return "include", "All five criteria met."


def _scored(label):
    return {
        "type": "object",
        "properties": {
            "evidence": {
                "type": "string",
                "description": f"Verbatim quote (<=40 words) supporting the {label} "
                               f"score, or 'none found'.",
            },
            "reasoning": {
                "type": "string",
                "description": "One line connecting the quote to the anchor you chose.",
            },
            "score": {"type": "integer", "enum": [0, 1, 2]},
            "comment": {
                "type": "string",
                "description": "Compressed noun phrases for the screener's audit. "
                               "Not a sentence.",
            },
        },
        "required": ["evidence", "reasoning", "score", "comment"],
        "additionalProperties": False,
    }


def _criterion_property(number):
    c = criteria.CRITERIA[number]
    return {
        "type": "object",
        "properties": {
            "evidence": {
                "type": "string",
                "description": f"Verbatim quote (<=40 words) bearing on criterion "
                               f"{number} ({c['short']}), or 'none found'.",
            },
            "reasoning": {
                "type": "string",
                "description": "One line connecting the quote to the requirement.",
            },
            "verdict": {"type": "string", "enum": criteria.VERDICTS},
            "comment": {
                "type": "string",
                "description": "Compressed noun phrases for the screener's audit. "
                               "Not a sentence.",
            },
        },
        "required": ["evidence", "reasoning", "verdict", "comment"],
        "additionalProperties": False,
    }


def build_schema():
    properties = {}
    for number in sorted(criteria.CRITERIA):
        properties[f"criterion_{number}"] = _criterion_property(number)
    properties.update({
        "publication_type": {"type": "string", "enum": PAPER_TYPES},
        "publication_type_evidence": {
            "type": "string",
            "description": "What in the document establishes the type (section "
                           "heading, structure, self-description).",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to 10 topical keywords.",
        },
    })
    for key, desc in SCOPE_FIELDS:
        properties[f"scope_{key}"] = {
            "type": "string",
            "description": f"The {desc} the paper's argument depends on, or 'NA'.",
        }
    properties["scope_other"] = {
        "type": "string",
        "description": "Any other dimension the argument is specific to, or 'NA'.",
    }
    for key, label, _q, _a in DIMENSIONS:
        properties[key] = _scored(label)
    properties["challenges"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Challenges or issues in modeling for public health that the "
                       "paper explicitly discusses. One short phrase each. Empty "
                       "array if none.",
    }
    properties["recommendations"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Recommendations or future research directions the paper "
                       "explicitly makes. One short phrase each. Empty array if none.",
    }
    properties["decision"] = {
        "type": "string",
        "enum": ["include", "exclude", "uncertain"],
        "description": "Overall screening decision, following from the five "
                       "criterion verdicts: include only if all five are met.",
    }
    properties["decision_rationale"] = {
        "type": "string",
        "description": "One sentence. For 'uncertain', state precisely what would "
                       "settle it.",
    }
    properties["screening_notes"] = {
        "type": "string",
        "description": "Anything the screener should know: PDF/record mismatch, "
                       "truncated or unreadable text, ambiguity in a judgement. "
                       "Empty string if nothing.",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
