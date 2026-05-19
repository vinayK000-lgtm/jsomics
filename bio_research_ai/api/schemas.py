from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any

from bio_research_ai.models import EvidenceLevel, ResearchMode


class EvidenceInput(BaseModel):
    source: str = Field(examples=["pubmed"])
    source_id: str = Field(examples=["PMID:123456"])
    title: str
    text: str
    url: str | None = None
    year: int | None = None
    quality: EvidenceLevel = EvidenceLevel.MEDIUM


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3)
    disease: str | None = None
    mode: ResearchMode = ResearchMode.AUTO
    evidence_level: EvidenceLevel = EvidenceLevel.MEDIUM
    max_results: int = Field(default=10, ge=1, le=50)
    inline_evidence: list[EvidenceInput] = Field(default_factory=list)
    omics: list[str] = Field(default_factory=lambda: ["literature", "biomarkers", "pathways", "drug_targets"])
    search_depth: str = Field(default="quick", pattern="^(quick|deep|systematic)$")


class EvidenceResponse(BaseModel):
    source: str
    source_id: str
    title: str
    url: str | None = None
    year: int | None = None
    quality: EvidenceLevel


class BiomarkerResponse(BaseModel):
    marker_id: str
    name: str
    marker_type: str
    direction: str | None
    score: float
    confidence: float
    evidence: list[EvidenceResponse]


class PathwayResponse(BaseModel):
    pathway_id: str
    name: str
    score: float
    confidence: float
    source: str
    evidence: list[EvidenceResponse]


class KnowledgeGraphTripleResponse(BaseModel):
    subject: str
    predicate: str
    object: str
    evidence: list[EvidenceResponse]
    confidence: float


class LiteratureFindingResponse(BaseModel):
    finding: str
    genes: list[str]
    diseases: list[str]
    drugs: list[str]
    pathways: list[str]
    relationships: list[KnowledgeGraphTripleResponse]
    evidence_grade: str
    consensus: str
    supporting_evidence: list[EvidenceResponse]


class ExistingDrugResponse(BaseModel):
    name: str
    mechanism: str | None = None
    stage: str
    indication: str | None = None


class DrugTargetResponse(BaseModel):
    gene: str
    protein: str
    target_class: str
    genetic_score: float
    biological_score: float
    druggability_score: float
    clinical_score: float
    total_score: float
    rationale: str
    existing_drugs: list[ExistingDrugResponse]
    combination_partners: list[str]
    safety_concerns: str | None = None
    uniprot_id: str | None = None
    pdb_structures: list[str]


class ProvenanceResponse(BaseModel):
    generated_by: str
    environment: str
    evidence_records: int
    sources: list[str]
    references: list[str]
    data_path: str | None = None
    took_ms: int | None = None
    from_cache: bool = False
    agent_status: dict[str, str] = Field(default_factory=dict)
    agent_timings_ms: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    llm_provider: str | None = None
    llm_enabled: bool = False
    omics: list[str] = Field(default_factory=list)
    job_id: str | None = None


class ResearchResponse(BaseModel):
    query: str
    disease: str | None
    agents_invoked: list[str]
    executive_summary: str
    confidence_overall: str
    answer: str
    confidence: float
    biomarkers: list[BiomarkerResponse]
    pathways: list[PathwayResponse]
    drug_targets: list[DrugTargetResponse]
    literature_findings: list[LiteratureFindingResponse]
    knowledge_graph_triples: list[KnowledgeGraphTripleResponse]
    evidence: list[EvidenceResponse]
    limitations: list[str]
    caveats: list[str]
    cross_agent_insights: list[str]
    unified_references: list[str]
    suggested_next_queries: list[str]
    research_use_only: bool
    disclaimer: str
    provenance: ProvenanceResponse
