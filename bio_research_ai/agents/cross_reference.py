"""
JSOMICS — Cross-Reference Engine

THE CORE DIFFERENTIATOR.

Takes DEG results + literature findings and finds:
  1. Genes confirmed in both expression data AND literature
  2. Evidence strength score for each gene
  3. Confidence tier: HIGH (both) / MEDIUM (one track) / LOW (weak signal)
  4. Unified ranked target list
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CrossReferencedGene:
    symbol: str
    in_deg: bool
    in_literature: bool
    log2fc: float = 0.0
    padj: float = 1.0
    literature_hits: int = 0
    direction: str = ""          # up / down / unknown
    evidence_score: float = 0.0  # 0-1 composite score
    confidence_tier: str = ""    # HIGH / MEDIUM / LOW
    pathways: list[str] = field(default_factory=list)
    drug_associations: list[str] = field(default_factory=list)
    rationale: str = ""


class CrossReferenceEngine:
    """Cross-reference DEG results with literature findings."""

    def run(
        self,
        deg_results: list,          # list of DEGResult objects
        literature_genes: list[str], # genes from PubMed literature mining
        pathway_hits: dict[str, list[str]],  # gene -> list of pathways
        drug_hits: dict[str, list[str]],     # gene -> list of drugs
        padj_threshold: float = 0.05,
        log2fc_threshold: float = 1.0,
    ) -> list[CrossReferencedGene]:
        """
        Cross-reference all sources and return unified ranked gene list.
        """
        lit_set = {g.upper() for g in literature_genes}

        # Build DEG lookup
        deg_lookup: dict[str, object] = {}
        for r in deg_results:
            sym = r.gene_symbol.upper()
            if sym not in deg_lookup or r.padj < deg_lookup[sym].padj:
                deg_lookup[sym] = r

        # All unique genes across both sources
        all_genes = set(deg_lookup.keys()) | lit_set

        output = []
        for sym in all_genes:
            in_deg = sym in deg_lookup
            in_lit = sym in lit_set
            deg_r = deg_lookup.get(sym)

            log2fc = float(deg_r.log2_fold_change) if deg_r else 0.0
            padj = float(deg_r.padj) if deg_r else 1.0
            sig_deg = in_deg and padj < padj_threshold and abs(log2fc) >= log2fc_threshold
            lit_hits = literature_genes.count(sym.upper()) + literature_genes.count(sym.lower()) + literature_genes.count(sym)

            # Score components
            deg_score = 0.0
            if sig_deg:
                # -log10(padj) normalised, capped at 1
                import math
                deg_score = min(1.0, -math.log10(max(padj, 1e-10)) / 10)

            lit_score = min(1.0, lit_hits / 5.0)  # normalised by 5 hits = max

            # Composite: both tracks weighted equally
            if in_deg and in_lit:
                evidence_score = 0.6 * deg_score + 0.4 * lit_score
                confidence_tier = "HIGH" if sig_deg and lit_hits >= 2 else "MEDIUM"
            elif sig_deg:
                evidence_score = 0.4 * deg_score
                confidence_tier = "MEDIUM"
            elif lit_hits >= 3:
                evidence_score = 0.3 * lit_score
                confidence_tier = "MEDIUM"
            else:
                evidence_score = 0.1 * (deg_score + lit_score)
                confidence_tier = "LOW"

            direction = ""
            if in_deg:
                direction = "up" if log2fc > 0 else "down"

            rationale = self._build_rationale(sym, in_deg, in_lit, sig_deg, log2fc, lit_hits, confidence_tier)

            output.append(CrossReferencedGene(
                symbol=sym,
                in_deg=in_deg,
                in_literature=in_lit,
                log2fc=log2fc,
                padj=padj,
                literature_hits=lit_hits,
                direction=direction,
                evidence_score=evidence_score,
                confidence_tier=confidence_tier,
                pathways=pathway_hits.get(sym, []),
                drug_associations=drug_hits.get(sym, []),
                rationale=rationale,
            ))

        # Sort: HIGH first, then by evidence score
        tier_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        output.sort(key=lambda g: (tier_order.get(g.confidence_tier, 3), -g.evidence_score))

        return output

    def _build_rationale(self, sym, in_deg, in_lit, sig_deg, log2fc, lit_hits, tier):
        parts = []
        if sig_deg:
            direction = "upregulated" if log2fc > 0 else "downregulated"
            parts.append(f"{sym} is significantly {direction} (log2FC={log2fc:.2f}) in expression data")
        elif in_deg:
            parts.append(f"{sym} appears in expression data but does not meet significance threshold")
        if in_lit:
            parts.append(f"supported by {lit_hits} literature mentions")
        if tier == "HIGH":
            parts.append("HIGH CONFIDENCE: confirmed by both expression and literature evidence")
        return ". ".join(parts) + "."
