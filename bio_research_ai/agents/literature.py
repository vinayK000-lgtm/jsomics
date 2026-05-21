from __future__ import annotations

import re

from bio_research_ai.agents.biomarker import extract_gene_symbols, split_sentences
from bio_research_ai.models import Evidence, IngestionRecord, KnowledgeGraphTriple, LiteratureFinding


DRUG_PATTERN = re.compile(
    r"\b([A-Z]?[a-z]+(?:mab|nib|asib|parib|ciclib|limus|tinib|statin|platin|zumab))\b"
)

PATHWAY_PATTERN = re.compile(
    r"\b([A-Za-z0-9 -]*(?:pathway|signaling|signalling|cascade)[A-Za-z0-9 -]*)\b",
    re.IGNORECASE,
)


class LiteratureMiningAgent:
    """Extracts lightweight evidence themes and knowledge graph triples from records.

    This MVP intentionally uses deterministic rules so the API is testable offline. The
    extraction boundary is designed to be replaced by biomedical NER and relation models.
    """

    def analyze(
        self,
        records: list[IngestionRecord],
        query: str = "",
        disease: str | None = None,
        limit: int = 10,
    ) -> tuple[list[LiteratureFinding], list[KnowledgeGraphTriple]]:
        triples: list[KnowledgeGraphTriple] = []
        findings: list[LiteratureFinding] = []

        for record in records:
            evidence = record.to_evidence()
            entity_text = f"{record.title}. {record.text}"
            relationship_text = record.text
            genes = sorted(set(extract_gene_symbols(entity_text)))
            pathways = sorted(set(extract_pathway_mentions(entity_text)))
            drugs = sorted(set(extract_drug_mentions(entity_text)))
            diseases = sorted({item for item in (disease, record.disease) if item})
            record_triples = extract_relationships(
                text=relationship_text,
                evidence=evidence,
                genes=genes,
                drugs=drugs,
                pathways=pathways,
                disease=disease or record.disease,
            )
            triples.extend(record_triples)

            if not any((genes, pathways, drugs, record_triples)):
                continue

            findings.append(
                LiteratureFinding(
                    finding=summarize_finding(
                        evidence=evidence,
                        genes=genes,
                        drugs=drugs,
                        pathways=pathways,
                        disease=disease or record.disease,
                    ),
                    genes=genes,
                    diseases=diseases,
                    drugs=drugs,
                    pathways=pathways,
                    relationships=record_triples,
                    evidence_grade=grade_evidence(relationship_text),
                    consensus=classify_consensus(text=entity_text, supporting_records=1),
                    supporting_evidence=[evidence],
                )
            )

        deduped_triples = dedupe_triples(triples)
        findings = enrich_consensus(findings)
        return findings[:limit], deduped_triples[: limit * 3]


def extract_drug_mentions(text: str) -> list[str]:
    drugs = []
    for match in DRUG_PATTERN.findall(text):
        drug = match[:1].upper() + match[1:]
        if len(drug) < 5:
            continue
        drugs.append(drug)
    return drugs


def extract_pathway_mentions(text: str) -> list[str]:
    """Extract lightweight pathway phrases without the removed pathway agent module."""
    pathways = []
    for match in PATHWAY_PATTERN.findall(text):
        value = " ".join(match.split()).strip(" .,:;")
        if len(value) < 8 or len(value) > 90:
            continue
        pathways.append(value)
    return pathways


def extract_relationships(
    text: str,
    evidence: Evidence,
    genes: list[str],
    drugs: list[str],
    pathways: list[str],
    disease: str | None,
) -> list[KnowledgeGraphTriple]:
    triples: list[KnowledgeGraphTriple] = []
    for sentence in split_sentences(text):
        sentence_genes = [gene for gene in genes if re.search(rf"\b{re.escape(gene)}\b", sentence)]
        sentence_drugs = [
            drug for drug in drugs if re.search(rf"\b{re.escape(drug)}\b", sentence, re.IGNORECASE)
        ]
        sentence_pathways = [
            pathway for pathway in pathways if pathway.lower() in sentence.lower()
        ]
        predicate = infer_predicate(sentence)

        if disease and sentence_genes:
            for gene in sentence_genes:
                disease_predicate = "associated_with"
                if predicate in {"biomarker_for", "causes"}:
                    disease_predicate = predicate
                triples.append(
                    KnowledgeGraphTriple(
                        subject=gene,
                        predicate=disease_predicate,
                        object=disease,
                        evidence=[evidence],
                        confidence=0.55,
                    )
                )

        for gene in sentence_genes:
            for pathway in sentence_pathways:
                triples.append(
                    KnowledgeGraphTriple(
                        subject=gene,
                        predicate=predicate,
                        object=pathway,
                        evidence=[evidence],
                        confidence=0.6,
                    )
                )

        for drug in sentence_drugs:
            for gene in sentence_genes:
                triples.append(
                    KnowledgeGraphTriple(
                        subject=drug,
                        predicate="inhibits" if predicate in {"inhibits", "treats"} else predicate,
                        object=gene,
                        evidence=[evidence],
                        confidence=0.6,
                    )
                )
            if disease and not sentence_genes:
                triples.append(
                    KnowledgeGraphTriple(
                        subject=drug,
                        predicate="treats" if predicate in {"treats", "inhibits"} else predicate,
                        object=disease,
                        evidence=[evidence],
                        confidence=0.5,
                    )
                )

    return dedupe_triples(triples)


def infer_predicate(sentence: str) -> str:
    value = sentence.lower()
    if any(term in value for term in ("inhibit", "block", "antagonist", "suppress")):
        return "inhibits"
    if any(term in value for term in ("activat", "phosphorylat", "stimulat")):
        return "activates"
    if any(term in value for term in ("upregulat", "elevat", "increas", "overexpress", "high")):
        return "upregulates"
    if any(term in value for term in ("downregulat", "reduc", "decreas", "low")):
        return "downregulates"
    if any(term in value for term in ("treat", "therapy", "therapeutic", "response")):
        return "treats"
    if any(term in value for term in ("biomarker", "diagnostic marker", "predictive marker")):
        return "biomarker_for"
    if any(term in value for term in ("cause", "drive", "resistance", "confers")):
        return "causes"
    return "associated_with"


def grade_evidence(text: str) -> str:
    value = text.lower()
    if "meta-analysis" in value or "systematic review" in value:
        return "A"
    if any(term in value for term in ("randomized", "phase 3", "phase iii", "clinical trial")):
        return "B"
    if any(term in value for term in ("cohort", "case-control", "in vivo", "mouse", "mice")):
        return "C"
    return "D"


def classify_consensus(text: str, supporting_records: int) -> str:
    value = text.lower()
    if any(term in value for term in ("conflicting", "contradict", "inconsistent")):
        return "conflicting"
    if supporting_records >= 2:
        return "established"
    if any(term in value for term in ("emerging", "recent", "novel")):
        return "emerging"
    return "preliminary"


def summarize_finding(
    evidence: Evidence,
    genes: list[str],
    drugs: list[str],
    pathways: list[str],
    disease: str | None,
) -> str:
    entities = []
    if genes:
        entities.append(f"genes/proteins {', '.join(genes[:4])}")
    if pathways:
        entities.append(f"pathways {', '.join(pathways[:2])}")
    if drugs:
        entities.append(f"drugs {', '.join(drugs[:3])}")
    subject = "; ".join(entities) if entities else "biomedical entities"
    disease_text = f" in {disease}" if disease else ""
    return f"{evidence.source_id} links {subject}{disease_text}: {evidence.title}"


def enrich_consensus(findings: list[LiteratureFinding]) -> list[LiteratureFinding]:
    gene_counts: dict[str, int] = {}
    for finding in findings:
        for gene in finding.genes:
            gene_counts[gene] = gene_counts.get(gene, 0) + 1

    enriched = []
    for finding in findings:
        supporting_records = max([gene_counts.get(gene, 1) for gene in finding.genes] or [1])
        if finding.consensus == "conflicting":
            consensus = "conflicting"
        else:
            consensus = classify_consensus(
                text=finding.finding,
                supporting_records=supporting_records,
            )
        enriched.append(
            LiteratureFinding(
                finding=finding.finding,
                genes=finding.genes,
                diseases=finding.diseases,
                drugs=finding.drugs,
                pathways=finding.pathways,
                relationships=finding.relationships,
                evidence_grade=finding.evidence_grade,
                consensus=consensus,
                supporting_evidence=finding.supporting_evidence,
            )
        )
    return enriched


def dedupe_triples(triples: list[KnowledgeGraphTriple]) -> list[KnowledgeGraphTriple]:
    by_key: dict[tuple[str, str, str], KnowledgeGraphTriple] = {}
    for triple in triples:
        key = (triple.subject, triple.predicate, triple.object)
        if key not in by_key:
            by_key[key] = triple
            continue
        evidence = dedupe_evidence(by_key[key].evidence + triple.evidence)
        by_key[key] = KnowledgeGraphTriple(
            subject=triple.subject,
            predicate=triple.predicate,
            object=triple.object,
            evidence=evidence,
            confidence=max(by_key[key].confidence, triple.confidence),
        )
    return list(by_key.values())


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
