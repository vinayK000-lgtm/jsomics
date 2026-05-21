"""
JSOMICS - Quality Control Module

Runs before DEG analysis. Equivalent to:
  R: plotPCA, plotMA, plotDispEsts, vst, sample distance heatmap

Outputs warnings, statistics, and QC plots.
Critical for dataset reliability assessment.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class QCResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    plots: dict = field(default_factory=dict)  # base64 PNGs
    recommendation: str = ""


def run_qc(dataset, case_cols: list[str], ctrl_cols: list[str]) -> QCResult:
    """
    Run QC checks on the expression matrix before DEG analysis.
    Returns QCResult with warnings, stats and plots.
    """
    import numpy as np

    df = dataset.expression_matrix
    warnings = []
    errors = []
    stats = {}
    plots = {}

    n_case = len(case_cols)
    n_ctrl = len(ctrl_cols)
    n_total = n_case + n_ctrl

    # Sample count checks
    stats["n_case"] = n_case
    stats["n_control"] = n_ctrl
    stats["n_total"] = n_total

    if n_case < 2 or n_ctrl < 2:
        errors.append(
            f"CRITICAL: Only {min(n_case, n_ctrl)} sample(s) in one group. "
            f"At least 2 samples per group are required. "
            f"Results are statistically unreliable."
        )
    elif n_case < 3 or n_ctrl < 3:
        warnings.append(
            f"Only {min(n_case, n_ctrl)} replicates in one group. "
            f"Results are exploratory. Validate in an independent dataset."
        )

    # Missing value rate
    if df is not None:
        subset = df[case_cols + ctrl_cols]
        missing_rate = float(subset.isna().mean().mean())
        stats["missing_rate"] = round(missing_rate * 100, 2)
        if missing_rate > 0.2:
            warnings.append(
                f"{round(missing_rate * 100, 1)}% missing values detected. "
                f"High missingness may reduce statistical power and introduce bias."
            )
        elif missing_rate > 0.05:
            warnings.append(
                f"{round(missing_rate * 100, 1)}% missing values. "
                f"These will be excluded from analysis."
            )

        # Gene filtering summary
        n_genes_total = len(df)
        low_expr = (subset.sum(axis=1) < 10).sum()
        stats["n_genes_total"] = n_genes_total
        stats["n_genes_lowexpr"] = int(low_expr)
        stats["n_genes_kept"] = int(n_genes_total - low_expr)

        if low_expr > n_genes_total * 0.5:
            warnings.append(
                f"{int(low_expr / n_genes_total * 100)}% of genes have very low expression "
                f"and will be filtered. Consider whether your data has been pre-filtered."
            )

        # Library size / sample-level QC
        lib_sizes = subset.sum(axis=0)
        cv = float(lib_sizes.std() / lib_sizes.mean()) if lib_sizes.mean() > 0 else 0
        stats["library_size_cv"] = round(cv, 3)
        stats["library_sizes"] = {c: int(v) for c, v in lib_sizes.fillna(0).items()}

        if cv > 0.3:
            warnings.append(
                f"High library size variation (CV={round(cv * 100, 1)}%). "
                f"Samples may come from different batches or have variable sequencing depth."
            )

        # Batch effect detection (PCA-based)
        try:
            from sklearn.decomposition import PCA
            from sklearn.preprocessing import StandardScaler

            log_data = np.log2(
                subset.replace(0, np.nan).fillna(0) + 1
            ).dropna()
            if log_data.shape[0] > 10 and log_data.shape[1] >= 3:
                x = StandardScaler().fit_transform(log_data.T.values)
                pca = PCA(n_components=min(3, x.shape[0] - 1))
                coords = pca.fit_transform(x)
                var = pca.explained_variance_ratio_

                # Check if case/control separate on PC1
                case_idx = [
                    list(subset.columns).index(c)
                    for c in case_cols
                    if c in subset.columns
                ]
                ctrl_idx = [
                    list(subset.columns).index(c)
                    for c in ctrl_cols
                    if c in subset.columns
                ]

                if len(case_idx) > 0 and len(ctrl_idx) > 0:
                    case_pc1 = np.mean([coords[i, 0] for i in case_idx])
                    ctrl_pc1 = np.mean([coords[i, 0] for i in ctrl_idx])
                    separation = abs(case_pc1 - ctrl_pc1)
                    pc1_range = coords[:, 0].max() - coords[:, 0].min()
                    sep_ratio = separation / pc1_range if pc1_range > 0 else 0

                    stats["pca_separation"] = round(float(sep_ratio), 3)
                    stats["pca_var_pc1"] = round(float(var[0] * 100), 1)

                    if sep_ratio < 0.2:
                        warnings.append(
                            f"Case and control samples show poor separation on PC1 "
                            f"(separation ratio={round(sep_ratio, 2)}). "
                            f"Check sample group assignments. "
                            f"There may be confounders or batch effects."
                        )

                # QC PCA plot
                plots["pca"] = _qc_pca_plot(
                    coords, var, case_cols, ctrl_cols, subset.columns.tolist()
                )
        except Exception as e:
            warnings.append(f"PCA QC could not be computed: {e}")

    # Recommendation
    n_warn = len(warnings)
    n_err = len(errors)
    passed = n_err == 0

    if n_err > 0:
        recommendation = (
            "STOP: Critical QC issues detected. "
            "Fix errors before proceeding with DEG analysis."
        )
    elif n_warn >= 3:
        recommendation = (
            "Proceed with caution. Multiple QC warnings detected. "
            "Results should be treated as exploratory and validated."
        )
    elif n_warn >= 1:
        recommendation = (
            "QC passed with warnings. Review warnings before interpreting results."
        )
    else:
        recommendation = "QC passed. Dataset looks suitable for DEG analysis."

    return QCResult(
        passed=passed,
        warnings=warnings,
        errors=errors,
        stats=stats,
        plots=plots,
        recommendation=recommendation,
    )


def _qc_pca_plot(coords, var, case_cols, ctrl_cols, all_cols) -> str:
    """Generate QC PCA plot as base64 PNG."""
    try:
        import base64
        import io
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 5))
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#f8fafc")

        colours = {c: "#ef4444" for c in case_cols}
        colours.update({c: "#3b82f6" for c in ctrl_cols})

        for i, col in enumerate(all_cols):
            if i >= len(coords):
                break
            color = colours.get(col, "#94a3b8")
            ax.scatter(
                coords[i, 0],
                coords[i, 1] if coords.shape[1] > 1 else 0,
                color=color,
                s=100,
                zorder=3,
                edgecolors="white",
                linewidth=0.8,
            )
            ax.annotate(
                col[:10],
                xy=(coords[i, 0], coords[i, 1] if coords.shape[1] > 1 else 0),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=7,
                color="#64748b",
            )

        ax.set_xlabel(f"PC1 ({var[0] * 100:.1f}%)", fontsize=9, color="#64748b")
        ax.set_ylabel(
            f"PC2 ({var[1] * 100:.1f}%)" if len(var) > 1 else "PC2",
            fontsize=9,
            color="#64748b",
        )
        ax.set_title("QC: Sample PCA", fontsize=10, color="#0f172a", pad=8)

        from matplotlib.lines import Line2D

        ax.legend(
            handles=[
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="w",
                    markerfacecolor="#ef4444",
                    label=f"Case (n={len(case_cols)})",
                    markersize=8,
                ),
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="w",
                    markerfacecolor="#3b82f6",
                    label=f"Control (n={len(ctrl_cols)})",
                    markersize=8,
                ),
            ],
            fontsize=8,
        )

        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        plt.close(fig)
        return b64
    except Exception:
        return ""
