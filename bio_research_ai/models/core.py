from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EvidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResearchMode(StrEnum):
    AUTO = "auto"
    BIOMARKERS = "biomarkers"
    PATHWAYS = "pathways"
    DRUG_TARGETS = "drug_targets"
    LITERATURE = "literature"


@dataclass(frozen=True)
class Evidence:
    source: str
    source_id: str
    title: str
    text: str
    url: str | None = None
    year: int | None = None
    quality: EvidenceLevel = EvidenceLevel.MEDIUM


@dataclass(frozen=True)
class IngestionRecord:
    dataset: str
    record_id: str
    disease: str | None
    title: str
    text: str
    source_url: str | None = None
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_evidence(self, quality: EvidenceLevel = EvidenceLevel.MEDIUM) -> Evidence:
        year = self.metadata.get("year")
        return Evidence(
            source=self.dataset,
            source_id=self.record_id,
            title=self.title,
            text=self.text,
            url=self.source_url,
            year=year if isinstance(year, int) else None,
            quality=quality,
        )


@dataclass(frozen=True)
class BiomarkerCandidate:
    marker_id: str
    name: str
    marker_type: str
    direction: str | None
    score: float
    confidence: float
    evidence: list[Evidence]


@dataclass(frozen=True)
class PathwayHit:
    pathway_id: str
    name: str
    score: float
    confidence: float
    evidence: list[Evidence]
    source: str = "kegg"


@dataclass(frozen=True)
class KnowledgeGraphTriple:
    subject: str
    predicate: str
    object: str
    evidence: list[Evidence]
    confidence: float = 0.0


@dataclass(frozen=True)
class LiteratureFinding:
    finding: str
    genes: list[str] = field(default_factory=list)
    diseases: list[str] = field(default_factory=list)
    drugs: list[str] = field(default_factory=list)
    pathways: list[str] = field(default_factory=list)
    relationships: list[KnowledgeGraphTriple] = field(default_factory=list)
    evidence_grade: str = "D"
    consensus: str = "preliminary"
    supporting_evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class ExistingDrug:
    name: str
    mechanism: str | None = None
    stage: str = "unknown"
    indication: str | None = None


@dataclass(frozen=True)
class DrugTargetCandidate:
    gene: str
    protein: str
    target_class: str
    genetic_score: float
    biological_score: float
    druggability_score: float
    clinical_score: float
    total_score: float
    rationale: str
    existing_drugs: list[ExistingDrug] = field(default_factory=list)
    combination_partners: list[str] = field(default_factory=list)
    safety_concerns: str | None = None
    uniprot_id: str | None = None
    pdb_structures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchQuery:
    query: str
    disease: str | None = None
    mode: ResearchMode = ResearchMode.AUTO
    evidence_level: EvidenceLevel = EvidenceLevel.MEDIUM
    max_results: int = 10


@dataclass(frozen=True)
class ResearchReport:
    query: ResearchQuery
    answer: str
    executive_summary: str
    agents_invoked: list[str] = field(default_factory=list)
    confidence_overall: str = "low"
    biomarkers: list[BiomarkerCandidate] = field(default_factory=list)
    pathways: list[PathwayHit] = field(default_factory=list)
    drug_targets: list[DrugTargetCandidate] = field(default_factory=list)
    literature_findings: list[LiteratureFinding] = field(default_factory=list)
    knowledge_graph_triples: list[KnowledgeGraphTriple] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    cross_agent_insights: list[str] = field(default_factory=list)
    unified_references: list[str] = field(default_factory=list)
    suggested_next_queries: list[str] = field(default_factory=list)
    research_use_only: bool = True
    disclaimer: str = (
        "These findings are for research use. Clinical decisions require physician review "
        "and validated diagnostic tests."
    )
