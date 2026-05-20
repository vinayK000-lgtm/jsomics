"""
JSOMICS — GEO analysis router

POST /v1/geo/search    Search GEO datasets by keyword
POST /v1/geo/analyse   Run full DEG + literature + AI interpretation
"""

from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings

router = APIRouter()


class GEOSearchRequest(BaseModel):
    keyword: str = Field(min_length=2)
    limit: int = Field(default=10, ge=1, le=20)


class GEOAnalyseRequest(BaseModel):
    accession: str = Field(description="GEO accession e.g. GSE12345")
    disease: str = Field(description="Disease or condition being studied")
    case_samples: list[str] = Field(default=[], description="Sample IDs for case group")
    control_samples: list[str] = Field(default=[], description="Sample IDs for control group")
    padj_threshold: float = Field(default=0.1)
    log2fc_threshold: float = Field(default=0.58)
    literature_query: str | None = Field(default=None, description="Custom PubMed query (optional)")


@router.post("/search")
async def geo_search(
    body: GEOSearchRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Search GEO for RNA-seq datasets."""
    from bio_research_ai.ingestion.geo import GEOClient

    client = GEOClient(email=settings.NCBI_EMAIL)
    results = client.search(body.keyword, limit=body.limit)
    if not results:
        return {"datasets": [], "message": "No datasets found. Try different keywords."}
    return {"datasets": results, "total": len(results)}


@router.get("/fetch")
async def geo_fetch(
    accession: str,
    user: AuthUser = Depends(get_current_user),
):
    """Fetch GEO dataset metadata and sample list."""
    from bio_research_ai.ingestion.geo import GEOClient

    client = GEOClient(email=settings.NCBI_EMAIL)
    dataset = client.fetch_dataset(accession)
    if not dataset:
        raise HTTPException(404, f"Dataset {accession} not found or could not be parsed.")
    return {
        "accession": dataset.accession,
        "title": dataset.title,
        "summary": dataset.summary,
        "organism": dataset.organism,
        "platform": dataset.platform,
        "sample_count": dataset.sample_count,
        "matrix_type": dataset.matrix_type,
        "samples": [
            {
                "id": s.sample_id,
                "title": s.title,
                "characteristics": s.characteristics,
            }
            for s in dataset.samples
        ],
    }


@router.post("/analyse")
async def geo_analyse(
    body: GEOAnalyseRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Full multi-omics analysis:
    1. Fetch GEO dataset
    2. Run DEG analysis (DESeq2 or t-test)
    3. Run PubMed literature mining in parallel
    4. Cross-reference DEG genes with literature
    5. AI interpretation via GPT-4o-mini
    """
    from bio_research_ai.ingestion.geo import GEOClient, DEGAnalyser
    from bio_research_ai.agents.cross_reference import CrossReferenceEngine
    from bio_research_ai.agents.ai_interpreter import AIInterpreter
    from bio_research_ai.ingestion.pubmed import PubMedClient
    import asyncio
    import concurrent.futures

    # Fetch GEO dataset
    geo_client = GEOClient(email=settings.NCBI_EMAIL)
    dataset = geo_client.fetch_dataset(body.accession)
    if not dataset:
        raise HTTPException(404, f"Could not fetch {body.accession}")

    if dataset.expression_matrix is None:
        raise HTTPException(422, f"No expression matrix found in {body.accession}")

    # Auto-assign samples if not provided
    case_samples = body.case_samples
    control_samples = body.control_samples
    if not case_samples or not control_samples:
        case_samples, control_samples = _auto_assign_groups(dataset)
        if not case_samples or not control_samples:
            raise HTTPException(422, "Could not auto-detect case/control groups. Please specify sample IDs.")

    def _run_deg():
        analyser = DEGAnalyser()
        return analyser.analyse(
            dataset=dataset,
            case_samples=case_samples,
            control_samples=control_samples,
            disease=body.disease,
            padj_threshold=body.padj_threshold,
            log2fc_threshold=body.log2fc_threshold,
        )

    def _run_pubmed():
        pubmed_client = PubMedClient(email=settings.NCBI_EMAIL)
        query = body.literature_query or f"{body.disease} gene expression RNA-seq"
        try:
            records = pubmed_client.ingest(query=query, disease=body.disease, limit=50)
            return records, _extract_genes_from_records(records)
        except Exception as e:
            print(f"[GEO] PubMed error: {e}")
            return [], []

    loop = asyncio.get_event_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            deg_future = loop.run_in_executor(pool, _run_deg)
            pubmed_future = loop.run_in_executor(pool, _run_pubmed)
            deg, (lit_records, literature_genes) = await asyncio.gather(deg_future, pubmed_future)
    except ValueError as e:
        raise HTTPException(422, str(e))

    # Cross-reference
    xref = CrossReferenceEngine()
    deg_gene_list = [r for r in deg.results if r.significant]
    cross_refs = xref.run(
        deg_results=deg_gene_list,
        literature_genes=literature_genes,
        pathway_hits={},
        drug_hits={},
        padj_threshold=body.padj_threshold,
        log2fc_threshold=body.log2fc_threshold,
    )

    # AI interpretation
    interpreter = AIInterpreter()
    deg_for_ai = [
        {"symbol": r.gene_symbol, "log2fc": r.log2_fold_change, "padj": r.padj}
        for r in deg.results[:20]
    ]
    ai = interpreter.interpret(
        disease=body.disease,
        deg_genes=deg_for_ai,
        literature_genes=literature_genes[:30],
        pathways=[],
        deg_method=deg.method,
        deg_stats={"sig_up": deg.significant_up, "sig_down": deg.significant_down},
    )

    # Visualisations
    plots = {}
    try:
        from bio_research_ai.agents.deg_visualiser import (
            volcano_plot, ma_plot, pca_plot, heatmap_plot, PlotBundle
        )
        sig_results = [r for r in deg.results if r.significant]
        all_results = deg.results[:2000]  # cap for performance
        plots["volcano"] = volcano_plot(
            all_results,
            title=f"{body.disease} — {body.accession}",
            padj_threshold=body.padj_threshold,
            log2fc_threshold=body.log2fc_threshold,
        )
        plots["ma_plot"] = ma_plot(all_results, title=f"MA Plot — {body.accession}")
        plots["pca"]     = pca_plot(dataset, case_samples, control_samples)
        plots["heatmap"] = heatmap_plot(all_results, dataset, top_n=50)
    except Exception as e:
        print(f"[geo] visualisation error: {e}")

    # Functional enrichment on significant DEG gene symbols
    enrichment = []
    try:
        from bio_research_ai.agents.enrichment import run_enrichment
        sig_genes = list({r.gene_symbol for r in deg.results
                         if r.significant and len(r.gene_symbol) <= 10})[:200]
        if sig_genes:
            enr_results = run_enrichment(
                sig_genes,
                databases=[
                    "GO_Biological_Process_2023",
                    "KEGG_2021_Human",
                    "Reactome_2022",
                ],
                padj_threshold=0.05,
                top_n=20,
            )
            enrichment = [
                {
                    "term_id":       r.term_id,
                    "term_name":     r.term_name,
                    "database":      r.database,
                    "p_value":       round(r.p_value, 6),
                    "adjusted_p":    round(r.adjusted_p, 6),
                    "odds_ratio":    round(r.odds_ratio, 3),
                    "overlap_genes": r.overlap_genes[:10],
                    "gene_count":    r.gene_count,
                }
                for r in enr_results
            ]
    except Exception as e:
        print(f"[geo] enrichment error: {e}")

    # Build response
    return {
        "accession": body.accession,
        "disease": body.disease,
        "dataset": {
            "title": dataset.title,
            "organism": dataset.organism,
            "matrix_type": dataset.matrix_type,
            "sample_count": dataset.sample_count,
            "case_samples": case_samples,
            "control_samples": control_samples,
        },
        "deg": {
            "method": deg.method,
            "total_genes": deg.total_genes,
            "significant_up": deg.significant_up,
            "significant_down": deg.significant_down,
            "warnings": deg.warnings,
            "top_genes": [
                {
                    "symbol": r.gene_symbol,
                    "log2fc": round(r.log2_fold_change, 3),
                    "pvalue": round(r.pvalue, 6),
                    "padj": round(r.padj, 6),
                    "mean_expression": round(r.mean_expression, 2),
                    "significant": r.significant,
                    "direction": "up" if r.log2_fold_change > 0 else "down",
                }
                for r in deg.results[:100]
            ],
        },
        "literature": {
            "records_found": len(lit_records),
            "genes_mentioned": list(set(literature_genes))[:50],
        },
        "cross_reference": [
            {
                "symbol": g.symbol,
                "in_deg": g.in_deg,
                "in_literature": g.in_literature,
                "log2fc": round(g.log2fc, 3),
                "padj": round(g.padj, 6),
                "literature_hits": g.literature_hits,
                "direction": g.direction,
                "evidence_score": round(g.evidence_score, 3),
                "confidence_tier": g.confidence_tier,
                "pathways": g.pathways,
                "drug_associations": g.drug_associations,
                "rationale": g.rationale,
                "disclaimer": "Gene symbols extracted by regex pattern matching. Cross-check against HGNC database before reporting.",
            }
            for g in cross_refs[:50]
        ],
        "ai_interpretation": {
            "deg_summary": ai.deg_summary,
            "literature_summary": ai.literature_summary,
            "cross_reference": ai.cross_reference,
            "top_hypotheses": ai.top_hypotheses,
            "suggested_next": ai.suggested_next,
            "confidence": ai.confidence,
            "model": ai.model_used,
        },
        "plots": plots,
        "enrichment": enrichment,
    }


def _auto_assign_groups(dataset) -> tuple[list[str], list[str]]:
    """Try to auto-detect case/control groups from sample metadata."""
    case_keywords = {
        "disease", "tumor", "tumour", "cancer", "case", "patient",
        "affected", "treated", "knockdown", "knockout", "ko", "kd",
        "mutant", "mut", "shRNA", "siRNA", "overexpression", "OE",
        "stimulated", "infected", "diabetic", "fibrotic", "injured"
    }
    control_keywords = {
        "normal", "control", "ctrl", "healthy", "untreated", "wild",
        "wt", "wildtype", "mock", "scramble", "vehicle", "empty",
        "adjacent", "paired", "baseline", "naive", "uninduced"
    }
    case_samples, control_samples = [], []
    for s in dataset.samples:
        text = (s.title + " " + " ".join(s.characteristics.values())).lower()
        is_case = any(kw.lower() in text for kw in case_keywords)
        is_ctrl = any(kw.lower() in text for kw in control_keywords)
        if is_case and not is_ctrl:
            case_samples.append(s.sample_id)
        elif is_ctrl and not is_case:
            control_samples.append(s.sample_id)
    return case_samples, control_samples


NOT_GENES = {
    "RNA", "DNA", "THE", "FOR", "AND", "WITH", "FROM", "THAT",
    "THIS", "WERE", "HAVE", "BEEN", "ALSO", "INTO", "SUCH",
    "USA", "UK", "CI", "OR", "IN", "OF", "IS", "AT", "BY",
    "AS", "AN", "BE", "DO", "GO", "UP", "TO", "ON", "NO",
    "PCR", "PBS", "BSA", "SDS", "PAGE", "ELISA", "FISH",
    "MRI", "CT", "PET", "TNF", "HIV", "HPV", "EBV", "CMV",
    "IHC", "WB", "IP", "IF", "LC", "MS", "NMR", "GEL",
}


def _extract_genes_from_records(records) -> list[str]:
    """Extract gene symbols from literature records using simple pattern matching."""
    import re
    gene_pattern = re.compile(r'\b([A-Z][A-Z0-9]{1,7})\b')
    genes = []
    for r in records:
        text = getattr(r, "text", "") + " " + getattr(r, "title", "")
        for match in gene_pattern.findall(text):
            if match not in NOT_GENES and len(match) >= 2:
                genes.append(match)
    return genes
