"""
JSOMICS - Gene ID annotation using MyGene.info API

Converts probe IDs, Ensembl IDs, Entrez IDs -> gene symbols + metadata.
No local database needed - uses the free MyGene.info REST API.

Supports:
  Probe IDs (Affymetrix, Illumina etc.)
  Ensembl gene IDs (ENSG00000...)
  Entrez gene IDs (integers)
  RefSeq IDs (NM_, NR_, NP_...)
  Gene symbols (pass-through with enrichment)
"""
from __future__ import annotations
import json
import urllib.request
from dataclasses import dataclass


@dataclass
class GeneAnnotation:
    input_id: str
    symbol: str
    name: str = ""
    ensembl_id: str = ""
    entrez_id: str = ""
    biotype: str = ""
    description: str = ""
    found: bool = False


def annotate_genes(
    gene_ids: list[str],
    species: str = "human",
) -> dict[str, GeneAnnotation]:
    """
    Annotate a list of gene IDs using MyGene.info API.
    Returns dict mapping input_id -> GeneAnnotation.
    Fast: batches up to 1000 IDs per request.
    """
    if not gene_ids:
        return {}

    # Detect ID type
    id_type = _detect_id_type(gene_ids[:10])
    results = {}

    # Batch into chunks of 500
    for i in range(0, len(gene_ids), 500):
        batch = gene_ids[i:i + 500]
        annotations = _query_mygene(batch, id_type, species)
        results.update(annotations)

    # Fill in missing with pass-through
    for gid in gene_ids:
        if gid not in results:
            results[gid] = GeneAnnotation(
                input_id=gid, symbol=gid, found=False
            )

    return results


def _detect_id_type(ids: list[str]) -> str:
    """Detect gene ID type from first few IDs."""
    sample = ids[0] if ids else ""
    if sample.startswith("ENSG"):
        return "ensembl.gene"
    if sample.startswith(("NM_", "NR_", "NP_", "XM_", "XR_")):
        return "refseq"
    if sample.replace(".", "").isdigit():
        return "entrezgene"
    if "_at" in sample or "AFFX" in sample:
        return "reporter"  # Affymetrix probe
    if sample.startswith("ILMN_"):
        return "reporter"  # Illumina probe
    return "symbol"  # default - treat as gene symbol


def _query_mygene(
    ids: list[str],
    id_type: str,
    species: str = "human",
) -> dict[str, GeneAnnotation]:
    """Query MyGene.info for a batch of IDs."""
    results = {}
    try:
        url = "https://mygene.info/v3/querymany"
        payload = json.dumps({
            "q": ids,
            "scopes": id_type,
            "fields": "symbol,name,ensembl.gene,entrezgene,type_of_gene,summary",
            "species": species,
            "dotfield": True,
        }).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "JSOMICS/1.0 (https://jsomics.com)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())

        for hit in data:
            input_id = hit.get("query", "")
            if hit.get("notfound") or not input_id:
                continue
            ensembl = hit.get("ensembl.gene", "")
            if isinstance(ensembl, list):
                ensembl = ensembl[0] if ensembl else ""
            results[input_id] = GeneAnnotation(
                input_id=input_id,
                symbol=hit.get("symbol", input_id),
                name=hit.get("name", ""),
                ensembl_id=str(ensembl),
                entrez_id=str(hit.get("entrezgene", "")),
                biotype=hit.get("type_of_gene", ""),
                description=hit.get("summary", "")[:200] if hit.get("summary") else "",
                found=True,
            )
    except Exception as e:
        print(f"[gene_annotator] MyGene.info error: {e}")

    return results
