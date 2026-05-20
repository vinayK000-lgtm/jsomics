"""
JSOMICS — DEG Visualisation Engine

Python equivalents of the R visualisations from the DESeq2 workflow:
  R: EnhancedVolcano()    → Python: volcano_plot()
  R: plotMA()             → Python: ma_plot()
  R: plotPCA()            → Python: pca_plot()
  R: pheatmap()           → Python: heatmap_plot()

All functions return base64-encoded PNG strings for embedding in the API response.
No file I/O — everything in memory for serverless compatibility.
"""

from __future__ import annotations
import base64
import io
from dataclasses import dataclass


@dataclass
class PlotBundle:
    """Collection of plots for a DEG analysis result."""
    volcano: str | None = None    # base64 PNG
    ma_plot: str | None = None    # base64 PNG
    pca: str | None = None        # base64 PNG
    heatmap: str | None = None    # base64 PNG


def _fig_to_b64(fig) -> str:
    """Convert matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#050a14", edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def volcano_plot(
    results: list,
    title: str = "Treated vs Control",
    padj_threshold: float = 0.1,
    log2fc_threshold: float = 0.58,
) -> str:
    """
    Enhanced volcano plot — equivalent to R EnhancedVolcano().
    X axis: log2FoldChange
    Y axis: -log10(padj)
    Colour: red=upregulated, blue=downregulated, grey=not significant
    Labels top 10 most significant genes.
    """
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        log2fc = [r.log2_fold_change for r in results]
        padj   = [max(r.padj, 1e-300) for r in results]  # avoid log(0)
        symbols = [r.gene_symbol for r in results]
        neg_log_padj = [-np.log10(p) for p in padj]

        # Colour assignment
        colours = []
        for fc, p in zip(log2fc, padj):
            if p < padj_threshold and fc >= log2fc_threshold:
                colours.append("#ef4444")   # upregulated — red
            elif p < padj_threshold and fc <= -log2fc_threshold:
                colours.append("#3b82f6")   # downregulated — blue
            else:
                colours.append("#334155")   # not significant — dark grey

        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor("#050a14")
        ax.set_facecolor("#080f1e")

        ax.scatter(log2fc, neg_log_padj, c=colours, alpha=0.65, s=14,
                   linewidths=0, rasterized=True)

        # Threshold lines
        ax.axhline(-np.log10(padj_threshold), color="#00d4aa",
                   linewidth=0.8, linestyle="--", alpha=0.6)
        ax.axvline(log2fc_threshold,  color="#00d4aa",
                   linewidth=0.8, linestyle="--", alpha=0.6)
        ax.axvline(-log2fc_threshold, color="#00d4aa",
                   linewidth=0.8, linestyle="--", alpha=0.6)

        # Label top 10 significant genes
        sig = sorted(
            [(i, padj[i]) for i in range(len(padj))
             if padj[i] < padj_threshold and abs(log2fc[i]) >= log2fc_threshold],
            key=lambda x: x[1]
        )[:10]
        for i, _ in sig:
            ax.annotate(
                symbols[i],
                xy=(log2fc[i], neg_log_padj[i]),
                xytext=(5, 5), textcoords="offset points",
                fontsize=6.5, color="#e2e8f0",
                fontfamily="monospace",
            )

        # Style
        up_n   = sum(1 for c in colours if c == "#ef4444")
        down_n = sum(1 for c in colours if c == "#3b82f6")
        ax.set_title(f"{title}\nUp: {up_n}  |  Down: {down_n}  |  "
                     f"padj<{padj_threshold}, |log2FC|>{log2fc_threshold}",
                     color="#e2e8f0", fontsize=10, pad=12)
        ax.set_xlabel("log2 Fold Change (Treated / Control)",
                      color="#94a3b8", fontsize=9)
        ax.set_ylabel("-log10(adjusted p-value)", color="#94a3b8", fontsize=9)
        ax.tick_params(colors="#64748b", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#1e3a5f")

        legend_patches = [
            mpatches.Patch(color="#ef4444", label=f"Up ({up_n})"),
            mpatches.Patch(color="#3b82f6", label=f"Down ({down_n})"),
            mpatches.Patch(color="#334155", label="NS"),
        ]
        ax.legend(handles=legend_patches, framealpha=0.3,
                  labelcolor="#e2e8f0", fontsize=8,
                  facecolor="#0c1220", edgecolor="#1e3a5f")

        plt.tight_layout()
        b64 = _fig_to_b64(fig)
        plt.close(fig)
        return b64
    except Exception as e:
        return ""


def ma_plot(results: list, title: str = "MA Plot") -> str:
    """
    MA plot — equivalent to R plotMA(res_shrink, ylim=c(-5,5)).
    X axis: mean expression (log10 baseMean)
    Y axis: log2FoldChange
    Significant genes coloured cyan.
    """
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        mean_expr = [max(r.mean_expression, 0.01) for r in results]
        log2fc    = [r.log2_fold_change for r in results]
        sig       = [r.significant for r in results]

        colours = ["#00d4aa" if s else "#334155" for s in sig]

        fig, ax = plt.subplots(figsize=(9, 6))
        fig.patch.set_facecolor("#050a14")
        ax.set_facecolor("#080f1e")

        ax.scatter(np.log10(mean_expr), log2fc, c=colours,
                   alpha=0.55, s=10, linewidths=0, rasterized=True)
        ax.axhline(0, color="#00d4aa", linewidth=1, alpha=0.5)
        ax.set_ylim(-5, 5)
        ax.set_title(title, color="#e2e8f0", fontsize=10, pad=10)
        ax.set_xlabel("log10(Mean Expression)", color="#94a3b8", fontsize=9)
        ax.set_ylabel("log2 Fold Change",       color="#94a3b8", fontsize=9)
        ax.tick_params(colors="#64748b", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#1e3a5f")

        plt.tight_layout()
        b64 = _fig_to_b64(fig)
        plt.close(fig)
        return b64
    except Exception as e:
        return ""


def pca_plot(dataset, case_cols: list[str], ctrl_cols: list[str]) -> str:
    """
    PCA plot — equivalent to R plotPCA(vsd, intgroup="condition").
    Uses VST-like log2 normalisation before PCA.
    """
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler

        df = dataset.expression_matrix
        if df is None:
            return ""

        all_samples = case_cols + ctrl_cols
        subset = df[all_samples].copy()
        subset = np.log2(subset.replace(0, np.nan).fillna(0) + 1)
        subset = subset.dropna()

        # PCA on samples (transpose: samples x genes)
        X = subset.T.values
        X = StandardScaler().fit_transform(X)
        pca = PCA(n_components=min(2, X.shape[0] - 1))
        coords = pca.fit_transform(X)
        var = pca.explained_variance_ratio_ * 100

        fig, ax = plt.subplots(figsize=(8, 6))
        fig.patch.set_facecolor("#050a14")
        ax.set_facecolor("#080f1e")

        labels = (["Treated"] * len(case_cols) + ["Control"] * len(ctrl_cols))
        colours_map = {"Treated": "#ef4444", "Control": "#3b82f6"}

        for i, (label, sample) in enumerate(zip(labels, all_samples)):
            ax.scatter(coords[i, 0], coords[i, 1] if coords.shape[1] > 1 else 0,
                       color=colours_map[label], s=120, zorder=3,
                       edgecolors="#e2e8f0", linewidth=0.5)
            ax.annotate(sample[:8], xy=(coords[i, 0],
                        coords[i, 1] if coords.shape[1] > 1 else 0),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=6.5, color="#94a3b8", fontfamily="monospace")

        ax.set_xlabel(f"PC1 ({var[0]:.1f}% variance)", color="#94a3b8", fontsize=9)
        ax.set_ylabel(f"PC2 ({var[1]:.1f}% variance)" if len(var) > 1 else "PC2",
                      color="#94a3b8", fontsize=9)
        ax.set_title("PCA — sample clustering by condition",
                     color="#e2e8f0", fontsize=10, pad=10)
        ax.tick_params(colors="#64748b", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#1e3a5f")

        from matplotlib.lines import Line2D
        legend = [
            Line2D([0],[0], marker="o", color="w", markerfacecolor="#ef4444",
                   label="Treated", markersize=8),
            Line2D([0],[0], marker="o", color="w", markerfacecolor="#3b82f6",
                   label="Control", markersize=8),
        ]
        ax.legend(handles=legend, framealpha=0.3, labelcolor="#e2e8f0",
                  facecolor="#0c1220", edgecolor="#1e3a5f", fontsize=8)

        plt.tight_layout()
        b64 = _fig_to_b64(fig)
        plt.close(fig)
        return b64
    except Exception as e:
        return ""


def heatmap_plot(results: list, dataset, top_n: int = 50) -> str:
    """
    Heatmap of top DEGs — equivalent to R pheatmap() on VST-normalised counts.
    Shows top_n most significant genes across all samples.
    """
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        df = dataset.expression_matrix
        if df is None:
            return ""

        sig = sorted(
            [r for r in results if r.significant],
            key=lambda r: r.padj
        )[:top_n]

        if len(sig) < 2:
            return ""

        gene_ids = [r.gene_id for r in sig]
        available = [g for g in gene_ids if g in df.index]
        if len(available) < 2:
            return ""

        mat = df.loc[available].copy()
        mat = np.log2(mat.replace(0, np.nan).fillna(0) + 1)
        # Z-score scaling per gene (equivalent to t(scale(t(mat))))
        mat_z = mat.sub(mat.mean(axis=1), axis=0).div(
            mat.std(axis=1).replace(0, 1), axis=0
        )

        fig_h = max(8, len(available) * 0.18)
        fig_w = max(8, mat_z.shape[1] * 0.5)
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("#050a14")

        sns.heatmap(
            mat_z,
            ax=ax,
            cmap="RdBu_r",
            center=0,
            vmin=-2, vmax=2,
            yticklabels=True,
            xticklabels=True,
            linewidths=0.3,
            linecolor="#1e3a5f",
            cbar_kws={"label": "Z-score", "shrink": 0.6},
        )
        ax.set_title(f"Top {len(available)} significant DEGs",
                     color="#e2e8f0", fontsize=10, pad=10)
        ax.tick_params(axis="y", labelsize=max(4, 8 - len(available)//10),
                       colors="#94a3b8")
        ax.tick_params(axis="x", labelsize=7, colors="#94a3b8", rotation=45)

        plt.tight_layout()
        b64 = _fig_to_b64(fig)
        plt.close(fig)
        return b64
    except Exception as e:
        return ""
