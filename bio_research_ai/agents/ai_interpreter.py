"""
JSOMICS — AI Interpretation Layer using GPT-4o-mini

Sits on top of DEG results and literature findings.
Uses GPT-4o-mini to:
  1. Interpret DEG results in biological context
  2. Summarise literature evidence for top genes
  3. Cross-reference DEG genes with literature findings
  4. Generate ranked hypothesis list with confidence
  5. Suggest follow-up analyses
"""

from __future__ import annotations
import os
import json
import httpx
from dataclasses import dataclass


@dataclass
class AIInterpretation:
    deg_summary: str           # Plain English summary of DEG results
    literature_summary: str    # Summary of literature findings
    cross_reference: str       # What genes appear in both and why it matters
    top_hypotheses: list[str]  # Ranked biological hypotheses
    suggested_next: list[str]  # Suggested follow-up analyses
    confidence: str            # high / medium / low
    model_used: str


class AIInterpreter:
    """GPT-4o-mini powered biological interpretation of multi-omics results."""

    MODEL = "gpt-4o-mini"
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")

    def interpret(
        self,
        disease: str,
        deg_genes: list[dict],        # top 20 DEG genes with log2FC, padj
        literature_genes: list[str],  # genes found in literature
        pathways: list[str],          # pathway names from KEGG
        deg_method: str,
        deg_stats: dict,
    ) -> AIInterpretation:
        """Generate AI interpretation of multi-omics findings."""

        if not self.api_key:
            return self._fallback_interpretation(disease, deg_genes, literature_genes)

        # Build concise context for the model
        top_up = [g for g in deg_genes if g.get("log2fc", 0) > 0][:10]
        top_down = [g for g in deg_genes if g.get("log2fc", 0) < 0][:10]
        overlap = [g["symbol"] for g in deg_genes if g["symbol"] in literature_genes]

        prompt = f"""You are a computational biologist analysing multi-omics data for {disease}.

DEG ANALYSIS ({deg_method}):
- Total significant genes: {deg_stats.get('sig_up', 0)} upregulated, {deg_stats.get('sig_down', 0)} downregulated
- Top upregulated: {', '.join(g['symbol'] + ' (log2FC=' + str(round(g['log2fc'],2)) + ')' for g in top_up[:5])}
- Top downregulated: {', '.join(g['symbol'] + ' (log2FC=' + str(round(g['log2fc'],2)) + ')' for g in top_down[:5])}

LITERATURE EVIDENCE:
- Genes with published evidence: {', '.join(literature_genes[:15])}

PATHWAY ANALYSIS:
- Enriched pathways: {', '.join(pathways[:8])}

CROSS-REFERENCE:
- Genes in BOTH DEG and literature: {', '.join(overlap[:10]) if overlap else 'None found yet'}

Provide a JSON response with these exact keys:
{{
  "deg_summary": "2-3 sentences interpreting the DEG results biologically",
  "literature_summary": "2-3 sentences on what literature says about these genes in {disease}",
  "cross_reference": "2-3 sentences on the significance of overlapping genes",
  "top_hypotheses": ["hypothesis 1", "hypothesis 2", "hypothesis 3"],
  "suggested_next": ["analysis 1", "analysis 2", "analysis 3"],
  "confidence": "high|medium|low"
}}

Be specific, use gene names, be concise. Focus on actionable insights."""

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 800,
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    }
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                return AIInterpretation(
                    deg_summary=data.get("deg_summary", ""),
                    literature_summary=data.get("literature_summary", ""),
                    cross_reference=data.get("cross_reference", ""),
                    top_hypotheses=data.get("top_hypotheses", []),
                    suggested_next=data.get("suggested_next", []),
                    confidence=data.get("confidence", "medium"),
                    model_used=self.MODEL,
                )
        except Exception as e:
            print(f"[AI] interpretation error: {e}")
            return self._fallback_interpretation(disease, deg_genes, literature_genes)

    def _fallback_interpretation(
        self,
        disease: str,
        deg_genes: list[dict],
        literature_genes: list[str],
    ) -> AIInterpretation:
        """Fallback when OpenAI API not configured."""
        overlap = [g["symbol"] for g in deg_genes if g["symbol"] in literature_genes]
        top_up = [g["symbol"] for g in deg_genes if g.get("log2fc", 0) > 0][:5]
        top_down = [g["symbol"] for g in deg_genes if g.get("log2fc", 0) < 0][:5]
        return AIInterpretation(
            deg_summary=f"DEG analysis identified {len(deg_genes)} significant genes in {disease}. Top upregulated: {', '.join(top_up)}. Top downregulated: {', '.join(top_down)}.",
            literature_summary=f"Literature search found evidence for {len(literature_genes)} genes in {disease}.",
            cross_reference=f"{len(overlap)} genes appear in both expression data and literature: {', '.join(overlap[:5])}. These represent high-confidence targets." if overlap else "No overlap detected yet. Consider ingesting more literature.",
            top_hypotheses=[
                f"Upregulation of {top_up[0]} may drive {disease} progression" if top_up else "Insufficient data for hypothesis",
                f"Cross-referenced genes represent validated targets for {disease}",
                "Pathway enrichment may reveal mechanistic insights",
            ],
            suggested_next=[
                "Validate top DEG hits in independent cohort",
                "Run pathway enrichment on significant gene list",
                "Check drug target databases for top hits",
            ],
            confidence="low",
            model_used="fallback",
        )
