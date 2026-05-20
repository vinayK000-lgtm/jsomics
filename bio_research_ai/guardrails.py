from __future__ import annotations

from bio_research_ai.models import Evidence, ResearchMode, ResearchQuery


RESEARCH_USE_DISCLAIMER = (
    "These findings are for research use. Clinical decisions require physician review "
    "and validated diagnostic tests."
)


def confidence_label(score: float) -> str:
    if score <= 0.0:
        return "exploratory — insufficient evidence"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "moderate"
    return "low"


def build_caveats(query: ResearchQuery, evidence: list[Evidence], limitations: list[str]) -> list[str]:
    caveats = list(limitations)
    if not evidence:
        caveats.append("No evidence records were available to ground biomedical claims.")
    if query.mode == ResearchMode.AUTO:
        caveats.append("Automatic routing is keyword-based in this version.")
    if any(item.source_id.lower().startswith("pmid:example") for item in evidence):
        caveats.append("Example inline evidence was supplied; do not treat it as curated literature.")
    caveats.append(RESEARCH_USE_DISCLAIMER)
    return dedupe_strings(caveats)


def suggested_next_queries(query: ResearchQuery) -> list[str]:
    disease = query.disease or "the disease"
    return [
        f"What patient-derived datasets support biomarkers in {disease}?",
        f"Which dysregulated pathways in {disease} overlap with approved drug targets?",
        f"What conflicting literature exists for the top findings in {disease}?",
    ]


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
