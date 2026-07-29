"""
The five inclusion/exclusion criteria, as written in the review protocol.

These are the criteria the title/abstract round in Rayyan was screened against,
so an exclusion recorded there as "Criterion 4" means criterion 4 below was not
met. That correspondence is what makes per-criterion validation possible: the
instrument can be asked which criteria a paper fails, and the answer compared
against which criteria a human cited.

Each criterion is stated as a requirement ("must") with an explicit exclusion
clause, so each is assessed as met / not met / unclear rather than scored. A
paper is included only if every criterion is met.
"""

CRITERIA = {
    1: {
        "short": "Scope",
        "requirement":
            "The paper must focus on the spread of infectious diseases in the "
            "context of pandemics, epidemics, or disease outbreaks.",
        "exclusion":
            "Papers that exclusively address non-communicable diseases, chronic "
            "diseases, or non-infectious health conditions are excluded.",
    },
    2: {
        "short": "Model-Based Approach",
        "requirement":
            "The paper must focus on mathematical models of infectious diseases, "
            "including but not limited to ordinary differential equations (ODE), "
            "agent-based models (ABM), stochastic models, statistical models, "
            "Bayesian models, and machine learning models (e.g. reinforcement "
            "learning, neural networks).",
        "exclusion":
            "Papers that exclusively describe data trends without referring to "
            "mathematical models (e.g. purely descriptive epidemiological "
            "studies, surveys, clinical studies) are excluded.",
    },
    3: {
        "short": "Public Health Relevance",
        "requirement":
            "The paper must discuss how mathematical models contribute to public "
            "health decision-making, including but not limited to policymaking, "
            "pandemic/epidemic preparedness, interventions, and resource "
            "allocation.",
        "exclusion":
            "Papers that exclusively focus on theoretical model development "
            "without discussing real-world applications or policy implications "
            "are excluded.",
    },
    4: {
        "short": "Challenges",
        "requirement":
            "The paper must include a critical discussion of the role, "
            "challenges, limitations, gaps, or future research directions in "
            "infectious disease modeling.",
        "exclusion":
            "Papers that exclusively present a model and its results without "
            "discussing its implications, strengths, or weaknesses are excluded.",
    },
    5: {
        "short": "Broader Perspective",
        "requirement":
            "The paper must go substantially beyond presenting a single model and "
            "its implications by taking a broader perspective on mathematical "
            "modeling, including but not limited to opinion pieces, perspective "
            "articles, editorials, reviews, and general discussions.",
        "exclusion":
            "Papers that exclusively present and discuss a single model, its "
            "results, or technical modeling aspects (e.g. parameter estimation, "
            "numerical solutions, computational efficiency, scenario-specific "
            "results) without discussing broader insights, challenges, or future "
            "directions in infectious disease modeling are excluded.",
    },
}

# How often each criterion was cited across the 117 title/abstract exclusions.
# Useful for weighting attention: criterion 5 did most of the work, criterion 3
# almost none, which says more about what reached that round than about the
# criteria themselves.
CITED_BY = {1: 20, 2: 25, 3: 3, 4: 47, 5: 84}

VERDICTS = ["met", "not met", "unclear"]


def as_prompt_block(numbers=None):
    """Render the criteria for a screening prompt."""
    blocks = []
    for number in sorted(numbers or CRITERIA):
        c = CRITERIA[number]
        blocks.append(
            f"**Criterion {number} -- {c['short']}**\n"
            f"{c['requirement']}\n"
            f"*Excluded:* {c['exclusion']}"
        )
    return "\n\n".join(blocks)
