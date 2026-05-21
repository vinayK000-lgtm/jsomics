"""
JSOMICS — GEO DEG background job router

The GEO analysis pipeline takes 60-120 seconds:
  - GEO matrix download from NCBI FTP (20-60s, file can be 50-200MB)
  - DEG analysis (5-30s depending on gene count)
  - PubMed literature mining (10-20s)
  - Cross-reference + AI interpretation (5-10s)
  - Enrichment via Enrichr API (5-10s)
  - Visualisation plots (5-10s)

Vercel free plan has a 10s timeout. This job system works around it:

  Step 1: POST /v1/geo/jobs          → create job, return job_id instantly
  Step 2: GET  /v1/geo/jobs/{id}     → poll status (frontend polls every 3s)
  Step 3: POST /v1/geo/jobs/{id}/run → execute the full pipeline (called by frontend)
  Step 4: GET  /v1/geo/jobs/{id}/result → fetch final result

On Vercel Pro (maxDuration=60) steps 1+3 can complete in one call.
On Vercel free, the frontend retries run until it gets a result.
"""

from __future__ import annotations
import uuid
import time
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, Field

from jsomics_api.auth import AuthUser, get_current_user
from jsomics_api.config import settings
from jsomics_api.services.job_store import (
    create_job, get_job, set_job, update_job, public_job
)

router = APIRouter()


class GEOJobRequest(BaseModel):
    accession: str = Field(description="GEO accession e.g. GSE12345")
    disease: str = Field(description="Disease or condition being studied")
    case_samples: list[str] = Field(default=[])
    control_samples: list[str] = Field(default=[])
    padj_threshold: float = Field(default=0.1)
    log2fc_threshold: float = Field(default=0.58)
    literature_query: str | None = None


@router.post("/jobs")
async def create_geo_job(
    body: GEOJobRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Create a GEO DEG analysis job. Returns job_id immediately."""
    job = await create_job(user.id, {
        "type": "geo_deg",
        **body.model_dump(mode="json"),
    })
    return public_job(job)


@router.get("/jobs/{job_id}")
async def get_geo_job(
    job_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Poll job status."""
    job = await get_job(job_id)
    if not job or job.get("user_id") != user.id:
        raise HTTPException(404, "Job not found")
    return public_job(job)


@router.post("/jobs/{job_id}/run")
async def run_geo_job(
    job_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Execute the GEO DEG pipeline for this job.
    Returns result directly if completed within timeout,
    or returns job status if still running.
    """
    job = await get_job(job_id)
    if not job or job.get("user_id") != user.id:
        raise HTTPException(404, "Job not found")

    # Return cached result if already done
    if job.get("status") == "done" and job.get("result"):
        return job["result"]

    # Already running — return current status
    if job.get("status") == "running":
        return {"job_id": job_id, "status": "running",
                "progress": job.get("progress", 0),
                "message": job.get("message", "Running...")}

    payload = job.get("payload", {})

    # Update status to running
    await update_job(job_id,
        status="running", progress=5,
        message="Starting GEO DEG analysis pipeline...")

    try:
        result = await _execute_geo_pipeline(job_id, payload)
        job["status"] = "done"
        job["progress"] = 100
        job["message"] = "Analysis complete"
        job["result"] = result
        job["error"] = None
        await set_job(job)
        return result
    except Exception as exc:
        await update_job(job_id,
            status="error", progress=100,
            message="Pipeline failed", error=str(exc))
        raise HTTPException(500, f"GEO analysis failed: {exc}")


@router.get("/jobs/{job_id}/result")
async def get_geo_result(
    job_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Fetch completed result."""
    job = await get_job(job_id)
    if not job or job.get("user_id") != user.id:
        raise HTTPException(404, "Job not found")
    if job.get("status") != "done":
        raise HTTPException(202, "Result not ready yet")
    return job["result"]


async def _execute_geo_pipeline(job_id: str, payload: dict) -> dict:
    """
    Full GEO DEG pipeline with progress updates at each stage.
    Equivalent to the R DESeq2 workflow:
      1. Fetch GEO matrix (GEOClient)
      2. Auto-detect or use provided sample groups
      3. DEG analysis (pydeseq2 or t-test fallback)
      4. PubMed literature mining (parallel)
      5. Cross-reference DEG x literature
      6. GO/KEGG enrichment via Enrichr
      7. AI interpretation via GPT-4o-mini
      8. Visualisation plots (volcano, MA, PCA, heatmap)
    """
    import asyncio
    import concurrent.futures

    from bio_research_ai.ingestion.geo import GEOClient, DEGAnalyser
    from bio_research_ai.agents.cross_reference import CrossReferenceEngine
    from bio_research_ai.agents.ai_interpreter import AIInterpreter
    from bio_research_ai.ingestion.pubmed import PubMedClient
    from jsomics_api.routers.geo import _auto_assign_groups, _extract_genes_from_records, NOT_GENES

    accession = payload["accession"]
    disease = payload["disease"]
    padj_threshold = payload.get("padj_threshold", 0.1)
    log2fc_threshold = payload.get("log2fc_threshold", 0.58)
    case_samples = payload.get("case_samples", [])
    control_samples = payload.get("control_samples", [])
    literature_query = payload.get("literature_query")

    # ── Stage 1: Fetch GEO dataset ──────────────────────────────────────────
    await update_job(job_id, progress=10,
        message=f"Downloading GEO matrix for {accession} from NCBI FTP...")

    geo_client = GEOClient(email=settings.NCBI_EMAIL)
    dataset = geo_client.fetch_dataset(accession)
    if not dataset:
        raise ValueError(f"Dataset {accession} not found or could not be parsed. "
                         "Check the accession number is correct and is an RNA-seq dataset.")

    if dataset.expression_matrix is None:
        raise ValueError(f"No expression matrix found in {accession}. "
                         "The dataset may not have a series matrix file.")

    await update_job(job_id, progress=20,
        message=f"Dataset loaded: {dataset.title[:60]}... "
                f"({dataset.sample_count} samples, {dataset.matrix_type})")

    # ── Stage 2: Assign sample groups ───────────────────────────────────────
    if not case_samples or not control_samples:
        case_samples, control_samples = _auto_assign_groups(dataset)
    if not case_samples or not control_samples:
        raise ValueError(
            "Could not auto-detect case/control groups from sample metadata. "
            "Please fetch the dataset first and specify sample IDs manually."
        )

    await update_job(job_id, progress=25,
        message=f"Sample groups: {len(case_samples)} case, "
                f"{len(control_samples)} control. Running DEG + literature in parallel...")

    # Stage 2b: QC check
    await update_job(job_id, progress=26,
        message="Running QC checks - sample count, missing values, PCA...")

    try:
        from bio_research_ai.agents.qc import run_qc
        qc_result = run_qc(dataset, case_samples, control_samples)

        if not qc_result.passed:
            raise ValueError(
                "QC FAILED: " + " | ".join(qc_result.errors)
            )

        if qc_result.warnings:
            print(f"[QC] {len(qc_result.warnings)} warnings: "
                  f"{qc_result.warnings[0]}")
    except ImportError:
        qc_result = None

    # ── Stage 3+4: DEG analysis + PubMed (parallel) ────────────────────────
    def _run_deg():
        analyser = DEGAnalyser()
        return analyser.analyse(
            dataset=dataset,
            case_samples=case_samples,
            control_samples=control_samples,
            disease=disease,
            padj_threshold=padj_threshold,
            log2fc_threshold=log2fc_threshold,
        )

    def _run_pubmed():
        client = PubMedClient(email=settings.NCBI_EMAIL)
        query = literature_query or f"{disease} gene expression RNA-seq biomarkers"
        try:
            records = client.ingest(query=query, disease=disease, limit=50)
            return records, _extract_genes_from_records(records)
        except Exception as e:
            print(f"[geo_jobs] PubMed error: {e}")
            return [], []

    loop = asyncio.get_event_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            deg_fut    = loop.run_in_executor(pool, _run_deg)
            pubmed_fut = loop.run_in_executor(pool, _run_pubmed)
            deg, (lit_records, literature_genes) = await asyncio.gather(
                deg_fut, pubmed_fut
            )
    except ValueError as e:
        raise ValueError(str(e))

    # Stage 3b: Gene annotation
    await update_job(job_id, progress=52,
        message="Annotating gene IDs via MyGene.info...")
    try:
        from bio_research_ai.agents.gene_annotator import annotate_genes
        gene_ids = [r.gene_symbol for r in deg.results[:500]]
        annotations = annotate_genes(gene_ids, species="human")
        # Update gene symbols in DEG results
        for r in deg.results:
            ann = annotations.get(r.gene_symbol)
            if ann and ann.found and ann.symbol:
                r.gene_symbol = ann.symbol
    except Exception as e:
        print(f"[geo_jobs] gene annotation: {e}")
        annotations = {}

    await update_job(job_id, progress=55,
        message=f"DEG done: {deg.significant_up}↑ {deg.significant_down}↓ significant. "
                f"PubMed: {len(lit_records)} records. Cross-referencing...")

    # ── Stage 5: Cross-reference ─────────────────────────────────────────────
    xref_engine = CrossReferenceEngine()
    cross_refs = xref_engine.run(
        deg_results=[r for r in deg.results if r.significant],
        literature_genes=literature_genes,
        pathway_hits={},
        drug_hits={},
        padj_threshold=padj_threshold,
        log2fc_threshold=log2fc_threshold,
    )

    high_conf = sum(1 for g in cross_refs if g.confidence_tier == "HIGH")
    await update_job(job_id, progress=65,
        message=f"Cross-reference: {high_conf} HIGH confidence targets. "
                f"Running GO/KEGG enrichment...")

    # ── Stage 6: Functional enrichment ──────────────────────────────────────
    enrichment = []
    try:
        from bio_research_ai.agents.enrichment import run_enrichment
        sig_genes = list({
            r.gene_symbol for r in deg.results
            if r.significant and 2 <= len(r.gene_symbol) <= 10
            and r.gene_symbol not in NOT_GENES
        })[:200]
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
        print(f"[geo_jobs] enrichment error: {e}")

    await update_job(job_id, progress=75,
        message=f"Enrichment: {len(enrichment)} terms. Running AI interpretation...")

    # ── Stage 7: AI interpretation ───────────────────────────────────────────
    interpreter = AIInterpreter()
    ai = interpreter.interpret(
        disease=disease,
        deg_genes=[
            {"symbol": r.gene_symbol,
             "log2fc": r.log2_fold_change,
             "padj": r.padj}
            for r in deg.results[:20]
        ],
        literature_genes=literature_genes[:30],
        pathways=[e["term_name"] for e in enrichment[:8]],
        deg_method=deg.method,
        deg_stats={
            "sig_up": deg.significant_up,
            "sig_down": deg.significant_down,
        },
    )

    await update_job(job_id, progress=85,
        message="Generating visualisations...")

    # ── Stage 8: Visualisations ──────────────────────────────────────────────
    plots = {}
    try:
        from bio_research_ai.agents.deg_visualiser import (
            volcano_plot, ma_plot, pca_plot, heatmap_plot
        )
        all_results = deg.results[:2000]
        plots["volcano"] = volcano_plot(
            all_results,
            title=f"{disease} — {accession}",
            padj_threshold=padj_threshold,
            log2fc_threshold=log2fc_threshold,
        )
        plots["ma_plot"] = ma_plot(all_results, title=f"MA Plot — {accession}")
        plots["pca"]     = pca_plot(dataset, case_samples, control_samples)
        plots["heatmap"] = heatmap_plot(all_results, dataset, top_n=50)
    except Exception as e:
        print(f"[geo_jobs] visualisation error: {e}")

    await update_job(job_id, progress=95, message="Finalising results...")

    # ── Final result ──────────────────────────────────────────────────────────
    return {
        "job_id": job_id,
        "accession": accession,
        "disease": disease,
        "dataset": {
            "title": dataset.title,
            "organism": dataset.organism,
            "matrix_type": dataset.matrix_type,
            "matrix_type_info": dataset.matrix_type_info,
            "sample_count": dataset.sample_count,
            "case_samples": case_samples,
            "control_samples": control_samples,
        },
        "qc": {
            "passed": qc_result.passed if qc_result else True,
            "recommendation": qc_result.recommendation if qc_result else "",
            "warnings": qc_result.warnings if qc_result else [],
            "errors": qc_result.errors if qc_result else [],
            "stats": qc_result.stats if qc_result else {},
            "plots": {
                "pca_qc": (qc_result.plots.get("pca", "") if qc_result else ""),
            },
        },
        "data_type_info": dataset.matrix_type_info,
        "gene_annotations": {
            gid: {
                "symbol": a.symbol,
                "name": a.name,
                "ensembl_id": a.ensembl_id,
                "entrez_id": a.entrez_id,
                "biotype": a.biotype,
                "description": a.description,
            }
            for gid, a in (annotations or {}).items()
            if a.found
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
                "symbol":           g.symbol,
                "in_deg":           g.in_deg,
                "in_literature":    g.in_literature,
                "log2fc":           round(g.log2fc, 3),
                "padj":             round(g.padj, 6),
                "literature_hits":  g.literature_hits,
                "direction":        g.direction,
                "evidence_score":   round(g.evidence_score, 3),
                "confidence_tier":  g.confidence_tier,
                "pathways":         g.pathways,
                "drug_associations": g.drug_associations,
                "rationale":        g.rationale,
                "disclaimer":       (
                    "Gene symbols extracted by regex pattern matching. "
                    "Verify against HGNC before reporting."
                ),
            }
            for g in cross_refs[:50]
        ],
        "ai_interpretation": {
            "deg_summary":        ai.deg_summary,
            "literature_summary": ai.literature_summary,
            "cross_reference":    ai.cross_reference,
            "top_hypotheses":     ai.top_hypotheses,
            "suggested_next":     ai.suggested_next,
            "confidence":         ai.confidence,
            "model":              ai.model_used,
        },
        "enrichment": enrichment,
        "plots": plots,
    }
