from __future__ import annotations
import sys
import os

"""
JSOMICS — GEO mRNA-seq ingestion and DEG analysis

Supports:
  - Raw count matrices (RNA-seq) — uses scipy t-test fallback in serverless runtime
  - Pre-normalised matrices (TPM, FPKM, log2-normalised) — uses directly
  - Auto-detects matrix type from GEO soft file metadata

Flow:
  1. Fetch GSE soft file from NCBI GEO FTP
  2. Parse sample metadata and expression matrix
  3. Detect matrix type (raw counts vs normalised)
  4. If raw: run t-test fallback with BH correction
  5. If normalised: run limma-style t-test via scipy
  6. Return ranked DEG list with log2FC, pvalue, padj
"""

import gzip
import io
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GEOSample:
    sample_id: str
    title: str
    source: str
    characteristics: dict = field(default_factory=dict)
    group: Optional[str] = None  # "case" or "control" — set by user or auto-detected


@dataclass 
class GEODataset:
    accession: str
    title: str
    summary: str
    organism: str
    platform: str
    sample_count: int
    matrix_type: str  # "raw_counts" | "normalised" | "unknown"
    samples: list[GEOSample] = field(default_factory=list)
    expression_matrix: Optional[pd.DataFrame] = None  # genes x samples


@dataclass
class DEGResult:
    gene_id: str
    gene_symbol: str
    log2_fold_change: float
    pvalue: float
    padj: float
    mean_expression: float
    significant: bool  # padj < 0.05 and |log2FC| > 1


@dataclass
class DEGAnalysis:
    accession: str
    disease: str
    method: str  # "deseq2" | "ttest"
    matrix_type: str
    total_genes: int
    significant_up: int
    significant_down: int
    results: list[DEGResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GEOClient:
    """Fetch and parse GEO datasets for mRNA-seq DEG analysis."""

    BASE_URL = "https://ftp.ncbi.nlm.nih.gov/geo/series"
    MATRIX_URL = "https://ftp.ncbi.nlm.nih.gov/geo/series/{stub}/{acc}/matrix/{acc}_series_matrix.txt.gz"
    SOFT_URL = "https://ftp.ncbi.nlm.nih.gov/geo/series/{stub}/{acc}/soft/{acc}_family.soft.gz"

    def __init__(self, email: str | None = None):
        self.email = email or "jsomics@research.com"

    def _stub(self, accession: str) -> str:
        """GSE123456 → GSE123nnn"""
        return accession[:-3] + "nnn"

    def search(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search GEO for RNA-seq datasets matching a keyword."""
        import urllib.parse
        query = urllib.parse.quote(f"{keyword}[Title] AND RNA-seq[All Fields] AND Homo sapiens[Organism]")
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term={query}&retmax={limit}&retmode=json&email={self.email}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                import json
                data = json.loads(r.read())
            ids = data.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            return self._fetch_summaries(ids)
        except Exception as e:
            print(f"[GEO] search error: {e}")
            return []

    def _fetch_summaries(self, ids: list[str]) -> list[dict]:
        """Fetch GEO dataset summaries for a list of IDs."""
        import json
        id_str = ",".join(ids)
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gds&id={id_str}&retmode=json&email={self.email}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            results = []
            for uid in ids:
                item = data.get("result", {}).get(uid, {})
                if item:
                    results.append({
                        "accession": item.get("accession", ""),
                        "title": item.get("title", ""),
                        "summary": item.get("summary", "")[:300],
                        "organism": item.get("taxon", ""),
                        "sample_count": item.get("n_samples", 0),
                        "platform": item.get("gpl", ""),
                    })
            return results
        except Exception as e:
            print(f"[GEO] summary fetch error: {e}")
            return []

    def fetch_dataset(self, accession: str) -> GEODataset | None:
        """Fetch a GEO dataset by accession number."""
        accession = accession.strip().upper()
        stub = self._stub(accession)
        url = self.MATRIX_URL.format(stub=stub, acc=accession)
        print(f"[GEO] Fetching matrix: {url}")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = gzip.decompress(r.read()).decode("utf-8", errors="replace")
            return self._parse_matrix_file(accession, raw)
        except Exception as e:
            print(f"[GEO] fetch error for {accession}: {e}")
            return None

    def _parse_matrix_file(self, accession: str, text: str) -> GEODataset:
        """Parse a GEO series matrix file into a GEODataset."""
        import numpy as np
        import pandas as pd

        lines = text.splitlines()
        metadata = {}
        samples = []
        sample_ids = []
        sample_titles = []
        sample_chars = []
        data_lines = []
        in_data = False

        for line in lines:
            if line.startswith("!Series_title"):
                metadata["title"] = line.split("\t", 1)[-1].strip('"')
            elif line.startswith("!Series_summary"):
                metadata["summary"] = line.split("\t", 1)[-1].strip('"')[:500]
            elif line.startswith("!Series_organism"):
                metadata["organism"] = line.split("\t", 1)[-1].strip('"')
            elif line.startswith("!Series_platform_id"):
                metadata["platform"] = line.split("\t", 1)[-1].strip('"')
            elif line.startswith("!Sample_geo_accession"):
                sample_ids = [x.strip('"') for x in line.split("\t")[1:]]
            elif line.startswith("!Sample_title"):
                sample_titles = [x.strip('"') for x in line.split("\t")[1:]]
            elif line.startswith("!Sample_characteristics_ch1"):
                chars = [x.strip('"') for x in line.split("\t")[1:]]
                sample_chars.append(chars)
            elif line.startswith("!series_matrix_table_begin"):
                in_data = True
            elif line.startswith("!series_matrix_table_end"):
                in_data = False
            elif in_data and not line.startswith("!"):
                data_lines.append(line)

        # Build samples
        for i, sid in enumerate(sample_ids):
            title = sample_titles[i] if i < len(sample_titles) else sid
            chars = {}
            for char_row in sample_chars:
                if i < len(char_row):
                    val = char_row[i]
                    if ":" in val:
                        k, v = val.split(":", 1)
                        chars[k.strip()] = v.strip()
            samples.append(GEOSample(
                sample_id=sid, title=title, source=title, characteristics=chars
            ))

        # Parse expression matrix
        matrix_df = None
        matrix_type = "unknown"
        if data_lines:
            try:
                header = data_lines[0].split("\t")
                rows = []
                gene_ids = []
                for line in data_lines[1:]:
                    parts = line.split("\t")
                    if len(parts) > 1:
                        gene_ids.append(parts[0].strip('"'))
                        try:
                            vals = [float(x) if x.strip() not in ("", "null", "NA") else np.nan 
                                    for x in parts[1:]]
                        except ValueError:
                            continue
                        rows.append(vals)
                if rows:
                    n_cols = min(len(r) for r in rows)
                    cols = sample_ids if sample_ids else header[1:n_cols+1]
                    matrix_df = pd.DataFrame(
                        [r[:n_cols] for r in rows],
                        index=gene_ids[:len(rows)],
                        columns=cols[:n_cols]
                    )
                    matrix_type = self._detect_matrix_type(matrix_df)
            except Exception as e:
                print(f"[GEO] matrix parse error: {e}")

        return GEODataset(
            accession=accession,
            title=metadata.get("title", accession),
            summary=metadata.get("summary", ""),
            organism=metadata.get("organism", "Homo sapiens"),
            platform=metadata.get("platform", ""),
            sample_count=len(samples),
            matrix_type=matrix_type,
            samples=samples,
            expression_matrix=matrix_df,
        )

    def _detect_matrix_type(self, df: pd.DataFrame) -> str:
        """
        Detect whether matrix contains raw counts or normalised values.
        Raw counts: integers, many zeros, large values (>1000)
        Normalised: floats, log2-scale (0-20 range) or TPM/FPKM (continuous)
        """
        import numpy as np

        sample = df.iloc[:, 0].dropna()
        if len(sample) == 0:
            return "unknown"
        # Check if all values are integers
        is_integer = np.all(sample == sample.astype(int))
        max_val = sample.max()
        mean_val = sample.mean()
        zero_frac = (sample == 0).mean()

        if is_integer and max_val > 1000 and zero_frac > 0.1:
            return "raw_counts"
        elif max_val <= 25 and mean_val < 15:
            return "normalised_log2"
        elif max_val > 25:
            return "normalised_tpm_fpkm"
        return "normalised"


class DEGAnalyser:
    """Run differential expression analysis on a GEODataset."""

    def analyse(
        self,
        dataset: GEODataset,
        case_samples: list[str],
        control_samples: list[str],
        disease: str = "",
        padj_threshold: float = 0.05,
        log2fc_threshold: float = 1.0,
    ) -> DEGAnalysis:
        """
        Run DEG analysis.
        Chooses method based on matrix type:
          raw_counts → t-test fallback with BH correction
          normalised → limma-style t-test with BH correction
        """
        df = dataset.expression_matrix
        if df is None:
            raise ValueError("Dataset has no expression matrix")

        # Subset to case/control columns
        all_cols = list(df.columns)
        case_cols = [c for c in case_samples if c in all_cols]
        ctrl_cols = [c for c in control_samples if c in all_cols]

        if len(case_cols) < 2 or len(ctrl_cols) < 2:
            raise ValueError(f"Need at least 2 samples per group. Got case={len(case_cols)}, control={len(ctrl_cols)}")

        warnings = []
        if dataset.matrix_type == "raw_counts":
            results, method = self._run_deseq2(df, case_cols, ctrl_cols, warnings)
        else:
            results, method = self._run_ttest(df, case_cols, ctrl_cols, dataset.matrix_type, warnings)

        # Apply thresholds
        for r in results:
            r.significant = (r.padj < padj_threshold and abs(r.log2_fold_change) >= log2fc_threshold)

        sig_up = sum(1 for r in results if r.significant and r.log2_fold_change > 0)
        sig_down = sum(1 for r in results if r.significant and r.log2_fold_change < 0)

        # Sort by significance then fold change
        results.sort(key=lambda r: (not r.significant, r.padj, -abs(r.log2_fold_change)))

        return DEGAnalysis(
            accession=dataset.accession,
            disease=disease,
            method=method,
            matrix_type=dataset.matrix_type,
            total_genes=len(results),
            significant_up=sig_up,
            significant_down=sig_down,
            results=results,
            warnings=warnings,
        )

    def _run_deseq2(
        self,
        df: pd.DataFrame,
        case_cols: list[str],
        ctrl_cols: list[str],
        warnings: list[str],
    ) -> tuple[list[DEGResult], str]:
        warnings.append(
            "DESeq2 (pydeseq2) is not available in this runtime. "
            "Using t-test with BH correction instead. "
            "For full DESeq2 analysis run locally with pydeseq2 installed."
        )
        return self._run_ttest(df, case_cols, ctrl_cols, "raw_counts_ttest_fallback", warnings)

    def _run_ttest(
        self,
        df: pd.DataFrame,
        case_cols: list[str],
        ctrl_cols: list[str],
        matrix_type: str,
        warnings: list[str],
    ) -> tuple[list[DEGResult], str]:
        """
        Limma-style t-test with Benjamini-Hochberg correction.
        For normalised data (log2, TPM, FPKM).
        If not log2, apply log2 transformation first.
        """
        import numpy as np
        import pandas as pd
        from scipy import stats
        from statsmodels.stats.multitest import multipletests

        subset = df[case_cols + ctrl_cols].copy()
        # Drop genes with too many NaN
        subset = subset.dropna(thresh=len(case_cols + ctrl_cols) // 2)

        # Log2 transform if not already log2
        if matrix_type in ("raw_counts_fallback", "normalised_tpm_fpkm"):
            subset = np.log2(subset.replace(0, np.nan) + 1)
            warnings.append("Applied log2(x+1) transformation before t-test.")

        case_data = subset[case_cols].values
        ctrl_data = subset[ctrl_cols].values

        # Compute fold change and t-test
        mean_case = np.nanmean(case_data, axis=1)
        mean_ctrl = np.nanmean(ctrl_data, axis=1)
        log2fc = mean_case - mean_ctrl  # already log2

        pvalues = []
        for i in range(len(subset)):
            c = case_data[i][~np.isnan(case_data[i])]
            k = ctrl_data[i][~np.isnan(ctrl_data[i])]
            if len(c) < 2 or len(k) < 2:
                pvalues.append(1.0)
                continue
            _, p = stats.ttest_ind(c, k, equal_var=False)
            pvalues.append(float(p) if not np.isnan(p) else 1.0)

        # BH correction
        _, padj, _, _ = multipletests(pvalues, method="fdr_bh")

        results = []
        for i, gene_id in enumerate(subset.index):
            results.append(DEGResult(
                gene_id=str(gene_id),
                gene_symbol=str(gene_id),
                log2_fold_change=float(log2fc[i]),
                pvalue=float(pvalues[i]),
                padj=float(padj[i]),
                mean_expression=float(np.nanmean([mean_case[i], mean_ctrl[i]])),
                significant=False,
            ))
        return results, "ttest_bh"
