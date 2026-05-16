from __future__ import annotations

import re
from collections import defaultdict

from bio_research_ai.models import Evidence, IngestionRecord, PathwayHit


PATHWAY_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9 -]{2,80}?(?:pathway|signaling|cascade|dysfunction|metabolism))\b",
    re.IGNORECASE,
)


class PathwayAnalystAgent:
    """Pathway extraction agent for KEGG/Reactome-style records and literature snippets."""

    def identify(self, records: list[IngestionRecord], limit: int = 10) -> list[PathwayHit]:
        grouped: dict[str, list[IngestionRecord]] = defaultdict(list)
        for record in records:
            if record.dataset.lower() == "kegg":
                grouped[record.title].append(record)
                continue
            for pathway_name in extract_pathway_mentions(record.text):
                grouped[pathway_name].append(record)

        hits: list[PathwayHit] = []
        for name, pathway_records in grouped.items():
            evidence = dedupe_evidence([record.to_evidence() for record in pathway_records[:5]])
            score = float(len(pathway_records))
            confidence = min(0.95, 0.3 + 0.12 * len(evidence))
            hits.append(
                PathwayHit(
                    pathway_id=stable_pathway_id(name),
                    name=name,
                    score=score,
                    confidence=confidence,
                    evidence=evidence,
                    source=pathway_records[0].dataset,
                )
            )

        hits.sort(key=lambda hit: (hit.score, hit.confidence), reverse=True)
        return hits[:limit]


def extract_pathway_mentions(text: str) -> list[str]:
    mentions = []
    for match in PATHWAY_PATTERN.findall(text):
        mention = re.sub(r"\s+", " ", match).strip(" .,:;")
        if len(mention.split()) > 10:
            continue
        mentions.append(mention)
    return mentions


def stable_pathway_id(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"pathway:{normalized[:80]}"


def dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    deduped: list[Evidence] = []
    for item in evidence:
        key = (item.source, item.source_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
