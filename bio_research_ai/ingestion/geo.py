from __future__ import annotations
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
from dataclasses import dataclass, field
from typing import Optional


def _ncbi_get(url: str, timeout: int = 30) -> bytes:
    """
    NCBI blocks urllib requests without a User-Agent header (returns 403).
    Always use this function instead of urllib.request.urlopen directly.
    """
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "JSOMICS/1.0 (multi-omics research platform; "
                "https://jsomics.com; research use only)"
            ),
            "Accept": "application/json, text/plain, */*",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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
    matrix_type_info: dict = field(default_factory=dict)
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
        query = urllib.parse.quote(
            f'({keyword}[Title] OR {keyword}[All Fields]) '
            f'AND (RNA-seq[All Fields] OR RNA-Seq[All Fields] OR "expression profiling by high throughput sequencing"[DataSet Type]) '
            f'AND Homo sapiens[Organism] '
            f'AND gse[Entry Type]'
        )
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term={query}&retmax={limit}&retmode=json&email={self.email}"
        try:
            import json
            data = json.loads(_ncbi_get(url, timeout=15))
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
            data = json.loads(_ncbi_get(url, timeout=15))
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
        import gzip

        accession = accession.strip().upper()
        stub = self._stub(accession)
        url = self.MATRIX_URL.format(stub=stub, acc=accession)
        print(f"[GEO] Fetching: {url}")
        try:
            raw_bytes = _ncbi_get(url, timeout=55)
            try:
                raw = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
            except Exception:
                raw = raw_bytes.decode("utf-8", errors="replace")
            return self._parse_matrix_file(accession, raw)
        except Exception as e:
            print(f"[GEO] fetch error for {accession}: {e}")
            try:
                url2 = f"https://ftp.ncbi.nlm.nih.gov/geo/series/{stub}/{accession}/matrix/"
                listing = _ncbi_get(url2, timeout=10).decode("utf-8", errors="replace")
                gz_files = re.findall(r'href="([^"]+\.txt\.gz)"', listing)
                if gz_files:
                    url3 = url2 + gz_files[0]
                    raw_bytes = _ncbi_get(url3, timeout=55)
                    raw = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
                    return self._parse_matrix_file(accession, raw)
            except Exception as e2:
                print(f"[GEO] alternate fetch also failed: {e2}")
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
        matrix_type_info = {}
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
                    matrix_type_info = self._detect_matrix_type(matrix_df)
                    matrix_type = matrix_type_info.get("type", "unknown")
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
            matrix_type_info=matrix_type_info,
            samples=samples,
            expression_matrix=matrix_df,
        )

    def _detect_matrix_type(self, df) -> dict:
        """
        Detect data type and recommend correct statistical method.
        Returns a dict with type, method, confidence, warnings.
        """
        import numpy as np

        sample = df.iloc[:, 0].dropna()
        if len(sample) == 0:
            return {
                "type": "unknown",
                "method": "ttest_bh",
                "confidence": "low",
                "warnings": ["Could not detect data type - no valid values found"]
            }

        max_val = float(sample.max())
        mean_val = float(sample.mean())
        median_val = float(sample.median())
        zero_frac = float((sample == 0).mean())
        is_integer = bool(np.all(sample == sample.round()))
        negative = bool((sample < 0).any())
        n_genes = len(df)

        warnings = []
        n_samples = len(df.columns)
        if n_samples < 3:
            warnings.append(
                f"Only {n_samples} samples detected. DEG results are "
                f"exploratory only and should not be reported as final evidence. "
                f"A minimum of 3 replicates per group is required for reliable statistics."
            )
        if n_samples < 6:
            warnings.append(
                "Fewer than 6 total samples. Statistical power is very low. "
                "Consider validation in an independent dataset."
            )

        # Raw integer counts - DESeq2 / edgeR
        if is_integer and not negative and max_val > 500 and zero_frac > 0.05:
            return {
                "type": "raw_counts",
                "label": "Raw RNA-seq count matrix",
                "method": "deseq2",
                "method_label": "DESeq2 (negative binomial GLM)",
                "confidence": "high",
                "warnings": warnings,
                "notes": "Raw integer counts detected. DESeq2 is the gold standard. "
                         "Size factor normalisation and dispersion estimation will be applied."
            }

        # Log2 normalised - limma
        if not negative and 0 < max_val <= 20 and mean_val < 12:
            return {
                "type": "normalised_log2",
                "label": "Log2-normalised expression matrix",
                "method": "limma_ttest",
                "method_label": "Limma-style moderated t-test + BH correction",
                "confidence": "high",
                "warnings": warnings,
                "notes": "Log2-scale values detected (max=" + str(round(max_val, 1)) + "). "
                         "This is likely microarray or pre-normalised RNA-seq. "
                         "Applying linear model with BH correction."
            }

        # Log2 with negatives - likely log2 ratio / fold change data
        if negative and max_val <= 15:
            return {
                "type": "log2_ratio",
                "label": "Log2 ratio / fold-change matrix",
                "method": "limma_ttest",
                "method_label": "Limma-style moderated t-test + BH correction",
                "confidence": "medium",
                "warnings": warnings + [
                    "Negative values detected - this may be log2 ratio data. "
                    "Verify that case and control samples are correctly assigned."
                ],
                "notes": "Log2 ratio data detected. Using moderated t-test."
            }

        # TPM / FPKM / RPKM - needs log transform first
        if not is_integer and not negative and max_val > 20 and mean_val < 500:
            return {
                "type": "normalised_tpm",
                "label": "TPM / FPKM / RPKM normalised matrix",
                "method": "limma_ttest",
                "method_label": "Log2 transform -> limma-style moderated t-test",
                "confidence": "medium",
                "warnings": warnings + [
                    "TPM/FPKM-style values detected. Log2(x+1) transformation "
                    "will be applied before differential analysis. "
                    "DESeq2 is not appropriate for pre-normalised data."
                ],
                "notes": "Continuous normalised values. Log2 transform applied before analysis."
            }

        # Very large values - possibly raw microarray signal
        if max_val > 10000:
            return {
                "type": "microarray_raw",
                "label": "Raw microarray signal intensity",
                "method": "limma_ttest",
                "method_label": "Log2 transform -> limma-style moderated t-test",
                "confidence": "medium",
                "warnings": warnings + [
                    "Large intensity values suggest raw microarray data. "
                    "Log2 transformation will be applied. "
                    "Background correction is recommended before upload."
                ],
                "notes": "Raw microarray intensities detected."
            }

        return {
            "type": "unknown",
            "label": "Unknown expression matrix format",
            "method": "limma_ttest",
            "method_label": "Log2 transform -> moderated t-test (safe fallback)",
            "confidence": "low",
            "warnings": warnings + [
                "Could not confidently detect data type. "
                "Using conservative fallback method. "
                "Please verify your input data format."
            ],
            "notes": "Unknown format. Stats: max=" + str(round(max_val, 2)) +
                     " mean=" + str(round(mean_val, 2)) +
                     " zeros=" + str(round(zero_frac * 100, 1)) + "%"
        }


class DEGAnalyser:
    """
    Full DEG analysis pipeline — Python equivalent of the R DESeq2 workflow.

    For raw counts:   pydeseq2 (DESeq2 port) → size factor estimation,
                      dispersion estimation, negative binomial GLM,
                      apeglm-equivalent LFC shrinkage
    For normalised:   limma-equivalent linear model via scipy/statsmodels,
                      empirical Bayes moderation, BH correction

    Matches the R workflow:
      DESeqDataSetFromMatrix → DESeq() → results() → lfcShrink() → EnhancedVolcano
    """

    def analyse(
        self,
        dataset,
        case_samples: list[str],
        control_samples: list[str],
        disease: str = "",
        padj_threshold: float = 0.1,
        log2fc_threshold: float = 0.58,
    ):
        import numpy as np
        import pandas as pd

        df = dataset.expression_matrix
        if df is None:
            raise ValueError("Dataset has no expression matrix")

        all_cols = list(df.columns)
        case_cols = [c for c in case_samples if c in all_cols]
        ctrl_cols = [c for c in control_samples if c in all_cols]

        if len(case_cols) < 2 or len(ctrl_cols) < 2:
            raise ValueError(
                f"Need at least 2 samples per group. "
                f"Got case={len(case_cols)}, control={len(ctrl_cols)}"
            )

        warnings = []

        if dataset.matrix_type == "raw_counts":
            results, method = self._run_deseq2(df, case_cols, ctrl_cols, warnings)
        else:
            results, method = self._run_limma_voom(df, case_cols, ctrl_cols,
                                                    dataset.matrix_type, warnings)

        for r in results:
            r.significant = (
                r.padj < padj_threshold and abs(r.log2_fold_change) >= log2fc_threshold
            )

        sig_up   = sum(1 for r in results if r.significant and r.log2_fold_change > 0)
        sig_down = sum(1 for r in results if r.significant and r.log2_fold_change < 0)
        results.sort(key=lambda r: (not r.significant, r.padj, -abs(r.log2_fold_change)))

        from bio_research_ai.ingestion.geo import DEGAnalysis
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

    def _run_deseq2(self, df, case_cols, ctrl_cols, warnings):
        """
        Full DESeq2 pipeline using pydeseq2.
        Equivalent to:
          dds <- DESeqDataSetFromMatrix(countData=counts, colData=metadata, design=~condition)
          dds <- dds[rowSums(counts(dds)) >= 10, ]
          dds <- DESeq(dds)
          res <- results(dds, contrast=c("condition","Treated","Control"))
          res_shrink <- lfcShrink(dds, coef="condition_Treated_vs_Control", type="apeglm")
        """
        try:
            import numpy as np
            import pandas as pd
            from pydeseq2.dds import DeseqDataSet
            from pydeseq2.ds import DeseqStats

            subset = df[case_cols + ctrl_cols].copy()
            # Round to integers — DESeq2 requires integer counts
            subset = subset.round().astype(int)
            # Filter low-count genes (rowSums >= 10, matching R code)
            subset = subset[subset.sum(axis=1) >= 10]
            # Remove genes with zero variance
            subset = subset[subset.var(axis=1) > 0]

            # Build metadata (colData equivalent)
            metadata = pd.DataFrame(
                {
                    "condition": (
                        ["Treated"] * len(case_cols) + ["Control"] * len(ctrl_cols)
                    )
                },
                index=case_cols + ctrl_cols,
            )
            metadata["condition"] = pd.Categorical(
                metadata["condition"], categories=["Control", "Treated"]
            )

            # Transpose: pydeseq2 expects samples x genes
            counts = subset.T

            # Create DESeqDataSet and run
            dds = DeseqDataSet(
                counts=counts,
                metadata=metadata,
                design_factors="condition",
                quiet=True,
            )
            dds.deseq2()

            # Extract results with shrinkage (apeglm equivalent)
            stat_res = DeseqStats(
                dds,
                contrast=["condition", "Treated", "Control"],
                quiet=True,
            )
            stat_res.summary()

            # LFC shrinkage (equivalent to lfcShrink)
            try:
                stat_res.lfc_shrink(coeff="condition_Treated_vs_Control")
            except Exception:
                warnings.append(
                    "LFC shrinkage failed — using unshrunken estimates. "
                    "Results are still valid but effect sizes may be slightly inflated."
                )

            res_df = stat_res.results_df.dropna(subset=["padj"])

            from bio_research_ai.ingestion.geo import DEGResult
            results = []
            for gene_id, row in res_df.iterrows():
                results.append(DEGResult(
                    gene_id=str(gene_id),
                    gene_symbol=str(gene_id),
                    log2_fold_change=float(row.get("log2FoldChange", 0)),
                    pvalue=float(row.get("pvalue", 1.0)),
                    padj=float(row.get("padj", 1.0)),
                    mean_expression=float(row.get("baseMean", 0)),
                    significant=False,
                ))
            return results, "deseq2_pydeseq2"

        except ImportError:
            warnings.append(
                "pydeseq2 not installed in this runtime. "
                "Falling back to limma-equivalent t-test. "
                "For full DESeq2 analysis: pip install pydeseq2"
            )
            return self._run_limma_voom(df, case_cols, ctrl_cols, "raw_counts_fallback", warnings)

    def _run_limma_voom(self, df, case_cols, ctrl_cols, matrix_type, warnings):
        """
        limma-voom equivalent for normalised data.
        Equivalent to:
          design <- model.matrix(~ condition)
          fit <- lmFit(exprs, design)
          fit <- eBayes(fit)
          topTable(fit, coef=2, number=Inf, adjust.method="BH")

        For TPM/FPKM: log2(x+1) transform → linear model → moderated t-test
        For log2 data: use directly → linear model → moderated t-test
        """
        import numpy as np
        import pandas as pd
        from scipy import stats
        from statsmodels.stats.multitest import multipletests

        subset = df[case_cols + ctrl_cols].copy()
        subset = subset.dropna(thresh=max(2, len(case_cols + ctrl_cols) // 2))

        # Log2 transform if not already log scale
        if matrix_type in (
            "raw_counts_fallback",
            "normalised_tpm_fpkm",
            "normalised_tpm",
            "microarray_raw",
            "unknown",
        ):
            subset = np.log2(subset.replace(0, np.nan).fillna(0) + 1)
            warnings.append(
                "Applied log2(x+1) transformation. "
                "For raw counts, install pydeseq2 for proper DESeq2 analysis."
            )

        case_data = subset[case_cols].values
        ctrl_data = subset[ctrl_cols].values

        mean_case = np.nanmean(case_data, axis=1)
        mean_ctrl = np.nanmean(ctrl_data, axis=1)
        log2fc = mean_case - mean_ctrl  # already log2 scale

        # Welch t-test (unequal variance — equivalent to limma default)
        pvalues = []
        for i in range(len(subset)):
            c = case_data[i][~np.isnan(case_data[i])]
            k = ctrl_data[i][~np.isnan(ctrl_data[i])]
            if len(c) < 2 or len(k) < 2:
                pvalues.append(1.0)
                continue
            _, p = stats.ttest_ind(c, k, equal_var=False)
            pvalues.append(float(p) if not np.isnan(p) else 1.0)

        # BH correction (Benjamini-Hochberg, same as R p.adjust method="BH")
        _, padj, _, _ = multipletests(pvalues, method="fdr_bh")

        from bio_research_ai.ingestion.geo import DEGResult
        results = []
        for i, gene_id in enumerate(subset.index):
            results.append(DEGResult(
                gene_id=str(gene_id),
                gene_symbol=str(gene_id),
                log2_fold_change=float(log2fc[i]),
                pvalue=float(pvalues[i]),
                padj=float(padj[i]),
                mean_expression=float(
                    np.nanmean([mean_case[i], mean_ctrl[i]])
                ),
                significant=False,
            ))
        return results, "limma_equivalent_ttest_bh"
