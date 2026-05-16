from __future__ import annotations

import re
from collections import defaultdict

from bio_research_ai.models import BiomarkerCandidate, Evidence, IngestionRecord


GENE_SYMBOL_PATTERN = re.compile(r"\b[A-Z][A-Z0-9-]{1,9}\b")
UP_WORDS = {"upregulated", "elevated", "increased", "overexpressed", "high"}
DOWN_WORDS = {"downregulated", "reduced", "decreased", "suppressed", "low"}
STOP_SYMBOLS = {
    "AND",
    "RNA",
    "DNA",
    "THE",
    "FOR",
    "WITH",
    "GENE",
    "GENES",
    "PATHWAY",
    "DISEASE",
    "PATIENTS",
    "CONTROL",
    "STUDY",
    "PMID",
}


class BiomarkerIdentifierAgent:
    """Rule-based MVP biomarker agent.

    Replace the candidate extraction step with PubMedBERT/BioBERT NER once training data
    and labeled spans are ready. The output shape should remain stable.
    """

    def identify(self, records: list[IngestionRecord], limit: int = 10) -> list[BiomarkerCandidate]:
        grouped: dict[str, list[tuple[IngestionRecord, str | None]]] = defaultdict(list)
        for record in records:
            for symbol in extract_gene_symbols(f"{record.title} {record.text}"):
                grouped[symbol].append((record, infer_direction(record.text, symbol)))

        candidates: list[BiomarkerCandidate] = []
        for symbol, mentions in grouped.items():
            evidence = [record.to_evidence() for record, _ in mentions[:5]]
            directions = [direction for _, direction in mentions if direction]
            direction = most_common(directions) if directions else None
            score = float(len(mentions))
            confidence = min(0.95, 0.25 + 0.15 * len({item.source_id for item in evidence}))
            candidates.append(
                BiomarkerCandidate(
                    marker_id=symbol,
                    name=symbol,
                    marker_type="gene_or_protein",
                    direction=direction,
                    score=score,
                    confidence=confidence,
                    evidence=dedupe_evidence(evidence),
                )
            )

        candidates.sort(key=lambda candidate: (candidate.score, candidate.confidence), reverse=True)
        return candidates[:limit]


def extract_gene_symbols(text: str) -> list[str]:
    symbols = []
    for match in GENE_SYMBOL_PATTERN.findall(text):
        symbol = match.strip("-")
        if symbol in STOP_SYMBOLS or symbol.isdigit():
            continue
        if len(symbol) <= 2 and not any(char.isdigit() for char in symbol):
            continue
        symbols.append(symbol)
    return symbols


def infer_direction(text: str, symbol: str) -> str | None:
    symbol_pattern = re.compile(rf"\b{re.escape(symbol)}\b", re.IGNORECASE)
    for sentence in split_sentences(text):
        if not symbol_pattern.search(sentence):
            continue
        sentence_lower = sentence.lower()
        if any(word in sentence_lower for word in UP_WORDS):
            return "up"
        if any(word in sentence_lower for word in DOWN_WORDS):
            return "down"
    return None


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def most_common(values: list[str]) -> str:
    return max(set(values), key=values.count)


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
