from __future__ import annotations

from bio_research_ai.agents.biomarker import BiomarkerIdentifierAgent
from bio_research_ai.agents.drug_target import DrugTargetDiscoveryAgent
from bio_research_ai.agents.literature import LiteratureMiningAgent
from bio_research_ai.agents.pathway import PathwayAnalystAgent
from bio_research_ai.guardrails import (
    build_caveats,
    confidence_label,
    suggested_next_queries,
)
from bio_research_ai.models import (
    Evidence,
    IngestionRecord,
    ResearchMode,
    ResearchQuery,
    ResearchReport,
)
from bio_research_ai.storage import InMemoryVectorStore, ResearchRepository


class ResearchOrchestrator:
    """Routes natural language research requests to specialist agents."""

    def __init__(
        self,
        repository: ResearchRepository,
        vector_store: InMemoryVectorStore,
        biomarker_agent: BiomarkerIdentifierAgent | None = None,
        pathway_agent: PathwayAnalystAgent | None = None,
        literature_agent: LiteratureMiningAgent | None = None,
        drug_target_agent: DrugTargetDiscoveryAgent | None = None,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.biomarker_agent = biomarker_agent or BiomarkerIdentifierAgent()
        self.pathway_agent = pathway_agent or PathwayAnalystAgent()
        self.literature_agent = literature_agent or LiteratureMiningAgent()
        self.drug_target_agent = drug_target_agent or DrugTargetDiscoveryAgent()

    @classmethod
    def from_records(cls, records: list[IngestionRecord]) -> "ResearchOrchestrator":
        repository = ResearchRepository()
        repository.add_many(records)
        vector_store = InMemoryVectorStore()
        vector_store.add_many(records)
        return cls(repository=repository, vector_store=vector_store)

    def research(self, research_query: ResearchQuery) -> ResearchReport:
        evidence_records = self._retrieve(research_query)
        evidence = [record.to_evidence(quality=research_query.evidence_level) for record in evidence_records]

        biomarkers = []
        pathways = []
        drug_targets = []
        literature_findings = []
        knowledge_graph_triples = []
        agents_to_run = select_agents(research_query)
        agents_invoked = ordered_agents(agents_to_run)

        if "biomarkers" in agents_to_run:
            biomarkers = self.biomarker_agent.identify(evidence_records, limit=research_query.max_results)
        if "pathways" in agents_to_run:
            pathways = self.pathway_agent.identify(evidence_records, limit=research_query.max_results)
        if "literature" in agents_to_run:
            literature_findings, knowledge_graph_triples = self.literature_agent.analyze(
                evidence_records,
                query=research_query.query,
                disease=research_query.disease,
                limit=research_query.max_results,
            )
        if "drug_targets" in agents_to_run:
            drug_targets = self.drug_target_agent.discover(
                records=evidence_records,
                biomarkers=biomarkers,
                pathways=pathways,
                limit=research_query.max_results,
            )

        answer = compose_answer(
            query=research_query,
            biomarkers=biomarkers,
            pathways=pathways,
            drug_targets=drug_targets,
            literature_findings=literature_findings,
            evidence=evidence,
        )
        confidence = report_confidence(
            marker_confidences=[item.confidence for item in biomarkers],
            pathway_confidences=[item.confidence for item in pathways],
            target_scores=[item.total_score for item in drug_targets],
            literature_count=len(literature_findings),
            evidence_count=len(evidence),
        )
        confidence_overall = confidence_label(confidence)
        limitations = []
        if not evidence:
            limitations.append("No local evidence matched the query. Ingest PubMed/KEGG data first.")
        if "drug_targets" in agents_to_run:
            limitations.append(
                "Drug target scoring is based on local evidence text; add ChEMBL, DrugBank, "
                "UniProt, PDB, and dependency-screen ingestion before production use."
            )
        caveats = build_caveats(research_query, evidence, limitations)

        return ResearchReport(
            query=research_query,
            answer=answer,
            executive_summary=answer,
            agents_invoked=agents_invoked,
            confidence_overall=confidence_overall,
            biomarkers=biomarkers,
            pathways=pathways,
            drug_targets=drug_targets,
            literature_findings=literature_findings,
            knowledge_graph_triples=knowledge_graph_triples,
            evidence=evidence,
            confidence=confidence,
            limitations=limitations,
            caveats=caveats,
            cross_agent_insights=derive_cross_agent_insights(
                biomarkers=biomarkers,
                pathways=pathways,
                drug_targets=drug_targets,
            ),
            unified_references=unified_references(evidence),
            suggested_next_queries=suggested_next_queries(research_query),
        )

    def _retrieve(self, research_query: ResearchQuery) -> list[IngestionRecord]:
        query_text = research_query.query
        if research_query.disease:
            query_text = f"{research_query.disease} {query_text}"

        vector_hits = self.vector_store.search(query_text, limit=research_query.max_results * 2)
        records = [hit.record for hit in vector_hits]
        if not records:
            records = self.repository.search_text(query_text, limit=research_query.max_results * 2)
        return dedupe_records(records)[: research_query.max_results * 2]


def compose_answer(
    query: ResearchQuery,
    biomarkers: list,
    pathways: list,
    drug_targets: list,
    literature_findings: list,
    evidence: list[Evidence],
) -> str:
    disease = query.disease or "the requested disease"
    if not evidence:
        return f"I do not have enough ingested evidence to answer for {disease} yet."

    parts = [f"For {disease}, I found {len(evidence)} evidence records."]
    if literature_findings:
        parts.append(f"Literature mining produced {len(literature_findings)} structured findings.")
    if biomarkers:
        marker_names = ", ".join(candidate.name for candidate in biomarkers[:5])
        parts.append(f"Top biomarker candidates: {marker_names}.")
    if pathways:
        pathway_names = ", ".join(pathway.name for pathway in pathways[:3])
        parts.append(f"Pathway signals: {pathway_names}.")
    if drug_targets:
        target_names = ", ".join(target.gene for target in drug_targets[:5])
        parts.append(f"Top therapeutic target leads: {target_names}.")
    parts.append(
        "These findings are for research use. Clinical decisions require physician review "
        "and validated diagnostic tests."
    )
    return " ".join(parts)


def report_confidence(
    marker_confidences: list[float],
    pathway_confidences: list[float],
    target_scores: list[float],
    literature_count: int,
    evidence_count: int,
) -> float:
    if evidence_count < 10:
        return 0.0

    target_confidences = [min(0.95, score / 10) for score in target_scores]
    literature_confidences = [min(0.85, 0.35 + literature_count * 0.05)] if literature_count else []
    values = marker_confidences + pathway_confidences + target_confidences + literature_confidences
    if not values:
        return 0.0
    evidence_boost = min(0.2, evidence_count * 0.02)
    return round(min(0.98, sum(values) / len(values) + evidence_boost), 3)


def dedupe_records(records: list[IngestionRecord]) -> list[IngestionRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[IngestionRecord] = []
    for record in records:
        key = (record.dataset, record.record_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def select_agents(research_query: ResearchQuery) -> set[str]:
    mode = research_query.mode
    if mode == ResearchMode.BIOMARKERS:
        return {"biomarkers", "pathways"}
    if mode == ResearchMode.PATHWAYS:
        return {"pathways"}
    if mode == ResearchMode.DRUG_TARGETS:
        return {"biomarkers", "pathways", "drug_targets", "literature"}
    if mode == ResearchMode.LITERATURE:
        return {"literature"}

    query_text = f"{research_query.disease or ''} {research_query.query}".lower()
    selected: set[str] = set()
    if any(term in query_text for term in ("biomarker", "marker", "diagnostic", "test")):
        selected.add("biomarkers")
    if any(term in query_text for term in ("pathway", "signaling", "mechanism", "cascade")):
        selected.add("pathways")
    if any(term in query_text for term in ("drug", "target", "therapy", "treatment", "inhibitor")):
        selected.update({"biomarkers", "pathways", "drug_targets"})
    if any(term in query_text for term in ("literature", "studies", "evidence", "research")):
        selected.add("literature")
    if any(term in query_text for term in ("everything", "comprehensive", "overview", "all about")):
        selected.update({"literature", "biomarkers", "pathways", "drug_targets"})
    if not selected:
        selected.update({"literature", "biomarkers", "pathways"})
    return selected


def ordered_agents(selected: set[str]) -> list[str]:
    order = ["literature", "biomarkers", "pathways", "drug_targets"]
    return [agent for agent in order if agent in selected]


def derive_cross_agent_insights(
    biomarkers: list,
    pathways: list,
    drug_targets: list,
) -> list[str]:
    insights: list[str] = []
    biomarker_names = {item.name for item in biomarkers}
    target_names = {item.gene for item in drug_targets}
    overlapping = sorted(biomarker_names & target_names)
    if overlapping:
        insights.append(
            "Genes appearing as both biomarker candidates and target leads: "
            + ", ".join(overlapping[:5])
            + "."
        )
    if pathways and target_names:
        insights.append(
            f"{len(pathways)} pathway signals can be used to contextualize "
            f"{len(target_names)} target leads."
        )
    return insights


def unified_references(evidence: list[Evidence]) -> list[str]:
    references = []
    seen: set[str] = set()
    for item in evidence:
        if item.source_id in seen:
            continue
        seen.add(item.source_id)
        references.append(item.source_id)
    return references
