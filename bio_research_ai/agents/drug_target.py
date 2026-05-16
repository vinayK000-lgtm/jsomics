from __future__ import annotations

import re
from collections import defaultdict

from bio_research_ai.agents.biomarker import extract_gene_symbols, split_sentences
from bio_research_ai.agents.literature import extract_drug_mentions
from bio_research_ai.models import (
    BiomarkerCandidate,
    DrugTargetCandidate,
    ExistingDrug,
    IngestionRecord,
    PathwayHit,
)


class DrugTargetDiscoveryAgent:
    """Ranks target leads from local evidence, biomarkers, and pathway hits."""

    def discover(
        self,
        records: list[IngestionRecord],
        biomarkers: list[BiomarkerCandidate] | None = None,
        pathways: list[PathwayHit] | None = None,
        stage: str | None = None,
        limit: int = 10,
    ) -> list[DrugTargetCandidate]:
        biomarkers = biomarkers or []
        pathways = pathways or []
        candidate_genes = collect_candidate_genes(records, biomarkers)
        if not candidate_genes:
            return []

        biomarker_names = {candidate.name for candidate in biomarkers}
        gene_records = records_by_gene(records, candidate_genes)
        candidates: list[DrugTargetCandidate] = []
        for gene in sorted(candidate_genes):
            supporting_records = gene_records.get(gene, [])
            if not supporting_records:
                continue
            text = " ".join(f"{record.title}. {record.text}" for record in supporting_records)
            genetic_score = score_genetic_evidence(text)
            biological_score = score_biological_evidence(
                gene=gene,
                text=text,
                is_biomarker=gene in biomarker_names,
                pathways=pathways,
            )
            druggability_score = score_druggability(text, gene)
            clinical_score = score_clinical_evidence(text)
            total_score = round(
                genetic_score + biological_score + druggability_score + clinical_score,
                2,
            )
            if total_score <= 0:
                continue

            candidates.append(
                DrugTargetCandidate(
                    gene=gene,
                    protein=gene,
                    target_class=infer_target_class(text, gene),
                    genetic_score=genetic_score,
                    biological_score=biological_score,
                    druggability_score=druggability_score,
                    clinical_score=clinical_score,
                    total_score=total_score,
                    rationale=build_rationale(
                        gene=gene,
                        genetic_score=genetic_score,
                        biological_score=biological_score,
                        druggability_score=druggability_score,
                        clinical_score=clinical_score,
                        stage=stage,
                    ),
                    existing_drugs=extract_existing_drugs(text, gene),
                    combination_partners=find_combination_partners(gene, supporting_records),
                    safety_concerns=infer_safety_concerns(text),
                    uniprot_id=infer_uniprot_id(supporting_records),
                    pdb_structures=extract_pdb_ids(text),
                )
            )

        candidates.sort(key=lambda candidate: candidate.total_score, reverse=True)
        return candidates[:limit]


def collect_candidate_genes(
    records: list[IngestionRecord],
    biomarkers: list[BiomarkerCandidate],
) -> set[str]:
    genes = {candidate.name for candidate in biomarkers}
    for record in records:
        genes.update(extract_gene_symbols(f"{record.title} {record.text}"))
    return genes


def records_by_gene(
    records: list[IngestionRecord],
    genes: set[str],
) -> dict[str, list[IngestionRecord]]:
    grouped: dict[str, list[IngestionRecord]] = defaultdict(list)
    for record in records:
        text = f"{record.title} {record.text}"
        for gene in genes:
            if re.search(rf"\b{re.escape(gene)}\b", text):
                grouped[gene].append(record)
    return grouped


def score_genetic_evidence(text: str) -> float:
    value = text.lower()
    score = 0.0
    if any(term in value for term in ("loss-of-function", "tumor suppressor", "deletion")):
        score += 1.0
    if any(term in value for term in ("gain-of-function", "activating mutation", "oncogene", "driver")):
        score += 1.0
    if any(term in value for term in ("gwas", "mendelian", "familial", "clinvar", "omim")):
        score += 1.0
    if score == 0 and any(term in value for term in ("mutation", "mutated", "variant", "amplification")):
        score += 1.0
    return min(3.0, score)


def score_biological_evidence(
    gene: str,
    text: str,
    is_biomarker: bool,
    pathways: list[PathwayHit],
) -> float:
    value = text.lower()
    score = 0.0
    if is_biomarker:
        score += 1.0
    if any(term in value for term in ("pathway", "signaling", "hub", "essential", "crispr")):
        score += 1.0
    if any(term in value for term in ("overexpressed", "upregulated", "elevated", "disease-specific")):
        score += 1.0
    if gene in " ".join(item.name for item in pathways):
        score = min(3.0, score + 0.5)
    return min(3.0, score)


def score_druggability(text: str, gene: str) -> float:
    value = text.lower()
    score = 0.0
    if any(term in value for term in ("binding pocket", "structure", "pdb", "kinase domain")):
        score += 1.0
    if any(term in value for term in ("inhibitor", "antibody", "small molecule", "drug target")):
        score += 1.0
    if extract_existing_drugs(text, gene):
        score = max(score, 1.0)
    return min(2.0, score)


def score_clinical_evidence(text: str) -> float:
    value = text.lower()
    score = 0.0
    if any(term in value for term in ("mouse", "mice", "animal model", "xenograft", "in vivo")):
        score += 1.0
    if any(term in value for term in ("clinical trial", "phase 1", "phase 2", "phase 3", "approved")):
        score += 1.0
    return min(2.0, score)


def infer_target_class(text: str, gene: str) -> str:
    value = text.lower()
    if "kinase" in value or gene.endswith("K"):
        return "kinase"
    if "receptor" in value or gene in {"EGFR", "ERBB2", "PDGFRA", "FGFR1", "FGFR2"}:
        return "receptor"
    if "transcription factor" in value:
        return "transcription_factor"
    if "enzyme" in value or "metabolism" in value:
        return "enzyme"
    if "ion channel" in value:
        return "ion_channel"
    return "other"


def extract_existing_drugs(text: str, gene: str) -> list[ExistingDrug]:
    drugs: dict[str, ExistingDrug] = {}
    gene_pattern = re.compile(rf"\b{re.escape(gene)}\b")
    for sentence in split_sentences(text):
        if not gene_pattern.search(sentence):
            continue
        mechanism = infer_drug_mechanism(sentence, gene)
        stage = infer_drug_stage(sentence)
        for drug in extract_drug_mentions(sentence):
            drugs[drug] = ExistingDrug(
                name=drug,
                mechanism=mechanism,
                stage=stage,
                indication=None,
            )
    return list(drugs.values())


def infer_drug_mechanism(sentence: str, gene: str) -> str:
    value = sentence.lower()
    if any(term in value for term in ("inhibit", "block", "antagonist")):
        return f"inhibits {gene}"
    if any(term in value for term in ("activate", "agonist")):
        return f"modulates {gene}"
    return f"associated with {gene}"


def infer_drug_stage(sentence: str) -> str:
    value = sentence.lower()
    if "approved" in value:
        return "approved"
    if "phase 3" in value or "phase iii" in value:
        return "phase3"
    if "phase 2" in value or "phase ii" in value:
        return "phase2"
    if "phase 1" in value or "phase i" in value:
        return "phase1"
    if "preclinical" in value:
        return "preclinical"
    return "unknown"


def find_combination_partners(gene: str, records: list[IngestionRecord]) -> list[str]:
    partners: dict[str, int] = {}
    for record in records:
        for symbol in extract_gene_symbols(f"{record.title} {record.text}"):
            if symbol == gene:
                continue
            partners[symbol] = partners.get(symbol, 0) + 1
    ranked = sorted(partners.items(), key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in ranked[:3]]


def infer_safety_concerns(text: str) -> str | None:
    value = text.lower()
    if "toxicity" in value or "adverse event" in value:
        return "Evidence text mentions toxicity or adverse events."
    if "broadly essential" in value:
        return "Potential on-target safety risk because the evidence describes broad essentiality."
    return None


def infer_uniprot_id(records: list[IngestionRecord]) -> str | None:
    for record in records:
        value = record.metadata.get("uniprot_id") or record.metadata.get("uniprot")
        if isinstance(value, str) and value:
            return value
    return None


def extract_pdb_ids(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b[0-9][A-Z0-9]{3}\b", text)))


def build_rationale(
    gene: str,
    genetic_score: float,
    biological_score: float,
    druggability_score: float,
    clinical_score: float,
    stage: str | None,
) -> str:
    stage_text = f" for {stage} disease" if stage else ""
    return (
        f"{gene} is prioritized{stage_text} from local evidence with "
        f"genetic={genetic_score}, biological={biological_score}, "
        f"druggability={druggability_score}, clinical={clinical_score}."
    )
