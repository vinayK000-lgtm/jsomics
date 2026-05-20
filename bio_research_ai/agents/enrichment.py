"""
JSOMICS — Functional Enrichment Analysis

Python equivalent of R clusterProfiler:
  enrichGO()   → GO enrichment via Enrichr API (gseapy)
  enrichKEGG() → KEGG enrichment via Enrichr API (gseapy)
  gseaGO()     → GSEA via gseapy

No local annotation databases needed — uses Enrichr REST API.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class EnrichmentResult:
    term_id: str
    term_name: str
    database: str           # GO_BP, GO_MF, GO_CC, KEGG, Reactome
    p_value: float
    adjusted_p: float
    odds_ratio: float
    overlap_genes: list[str] = field(default_factory=list)
    gene_count: int = 0


def run_enrichment(
    gene_symbols: list[str],
    databases: list[str] | None = None,
    padj_threshold: float = 0.05,
    top_n: int = 20,
) -> list[EnrichmentResult]:
    """
    Run functional enrichment using Enrichr API.
    Equivalent to R clusterProfiler::enrichGO + enrichKEGG.

    Databases:
      GO_Biological_Process_2023
      GO_Molecular_Function_2023
      KEGG_2021_Human
      Reactome_2022
      WikiPathway_2023_Human
    """
    if databases is None:
        databases = [
            "GO_Biological_Process_2023",
            "KEGG_2021_Human",
            "Reactome_2022",
        ]

    if not gene_symbols:
        return []

    try:
        import gseapy as gp
    except ImportError:
        return _enrichr_fallback(gene_symbols, databases, padj_threshold, top_n)

    results = []
    for db in databases:
        try:
            enr = gp.enrichr(
                gene_list=gene_symbols,
                gene_sets=db,
                outdir=None,
                verbose=False,
            )
            df = enr.results
            if df is None or df.empty:
                continue
            df = df[df["Adjusted P-value"] < padj_threshold].head(top_n)
            for _, row in df.iterrows():
                genes = str(row.get("Genes", "")).split(";")
                results.append(EnrichmentResult(
                    term_id=str(row.get("Term", "")).split(" ")[0],
                    term_name=str(row.get("Term", "")),
                    database=db,
                    p_value=float(row.get("P-value", 1.0)),
                    adjusted_p=float(row.get("Adjusted P-value", 1.0)),
                    odds_ratio=float(row.get("Odds Ratio", 0)),
                    overlap_genes=[g.strip() for g in genes if g.strip()],
                    gene_count=len(genes),
                ))
        except Exception as e:
            print(f"[enrichment] {db} failed: {e}")
            continue

    results.sort(key=lambda r: r.adjusted_p)
    return results


def _enrichr_fallback(gene_symbols, databases, padj_threshold, top_n):
    """Direct Enrichr REST API call when gseapy not available."""
    import json, urllib.request, urllib.parse

    ENRICHR_URL = "https://maayanlab.cloud/Enrichr"
    results = []
    try:
        # Add gene list
        payload = urllib.parse.urlencode(
            {"list": "\n".join(gene_symbols), "description": "JSOMICS DEG"}
        ).encode()
        req = urllib.request.urlopen(
            f"{ENRICHR_URL}/addList", data=payload, timeout=15
        )
        data = json.loads(req.read())
        user_list_id = data["userListId"]

        for db in databases:
            url = (
                f"{ENRICHR_URL}/enrich?userListId={user_list_id}"
                f"&backgroundType={urllib.parse.quote(db)}"
            )
            req = urllib.request.urlopen(url, timeout=15)
            data = json.loads(req.read())
            entries = data.get(db, [])[:top_n]
            for entry in entries:
                # Enrichr format: [rank, term, pval, zscore, combined, genes, adj_pval]
                if len(entry) < 7:
                    continue
                adj_p = float(entry[6]) if entry[6] else 1.0
                if adj_p > padj_threshold:
                    continue
                results.append(EnrichmentResult(
                    term_id=str(entry[1]).split(" ")[0],
                    term_name=str(entry[1]),
                    database=db,
                    p_value=float(entry[2]),
                    adjusted_p=adj_p,
                    odds_ratio=float(entry[3]) if entry[3] else 0.0,
                    overlap_genes=entry[5] if isinstance(entry[5], list)
                                  else str(entry[5]).split(";"),
                    gene_count=len(entry[5]) if isinstance(entry[5], list) else 0,
                ))
    except Exception as e:
        print(f"[enrichment] Enrichr fallback failed: {e}")
    return sorted(results, key=lambda r: r.adjusted_p)
