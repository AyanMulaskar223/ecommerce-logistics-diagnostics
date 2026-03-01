from __future__ import annotations

import matplotlib.axes
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy import stats


def optimize_memory_usage(
    df: pd.DataFrame,
    categorical_cols: list[str] | None = None,
    int_cols: list[str] | None = None,
    float_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Downcast DataFrame columns to the smallest safe types to minimize RAM.

    Applies three complementary downcasting strategies in sequence:

    1. **Integer columns** — ``pd.to_numeric(downcast="integer")`` shrinks each
       column to the smallest signed integer type whose range covers the actual
       min/max values (``int64`` → ``int32`` → ``int16`` → ``int8``).
       Example: ``is_valid_logistics`` (values: 0, 1) → ``int8`` (saves 87.5%).
    2. **Float columns** — ``pd.to_numeric(downcast="float")`` shrinks
       ``float64`` → ``float32`` where precision loss is acceptable for monetary
       BRL values and weight measurements at two-decimal accuracy.
    3. **Categorical columns** — low-cardinality string columns (state codes,
       flag labels) are cast to ``category`` (integer-mapped dictionary
       encoding), collapsing repeated string objects into a single shared pool.

    A per-column savings log is printed for full auditability.

    Args:
        df: Input DataFrame. Must have all quality-flag filters already applied
            (``is_valid_logistics == 1 and is_valid_product == 1``).
        categorical_cols: Low-cardinality string columns to encode as
            ``category``. Typical candidates: ``customer_state``,
            ``seller_state``, ``logistics_issue_reason``,
            ``product_issue_reason``.
        int_cols: Integer columns to downcast to smallest safe signed int type.
            Typical candidates: ``order_item_id``, ``is_valid_logistics``,
            ``is_valid_product``.
        float_cols: Float columns to downcast from ``float64`` → ``float32``.
            Typical candidates: ``price``, ``freight_value``,
            ``product_weight_g``, ``review_score``.

    Returns:
        A copy of the input DataFrame with all specified columns downcast.
        The original DataFrame is never mutated.

    Raises:
        ValueError: If any column listed in ``categorical_cols``, ``int_cols``,
            or ``float_cols`` is not present in ``df``.
    """
    df = df.copy()

    # ── Pre-flight: validate all requested columns exist ─────────────────────
    all_requested: list[str] = (
        list(categorical_cols or []) + list(int_cols or []) + list(float_cols or [])
    )
    missing = [c for c in all_requested if c not in df.columns]
    if missing:
        raise ValueError(
            f"Columns not found in DataFrame: {missing}. "
            "Check column names match the OBT schema exactly."
        )

    initial_memory = df.memory_usage(deep=True).sum() / (1024**2)
    col_log: list[tuple[str, str, str, float]] = []  # (col, before, after, saved_kb)

    # ── 1. Integer downcasting ────────────────────────────────────────────────
    # pd.to_numeric(downcast="integer") inspects the actual min/max of the
    # column and selects the smallest signed type that fits:
    #   int64 (-9.2e18 → 9.2e18) → int32 / int16 / int8 (-128 → 127)
    # order_item_id max ≈ 21  → int8  (saves 87.5% vs int64)
    # is_valid_*    values 0,1 → int8  (saves 87.5% vs int64)
    for col in int_cols or []:
        before_dtype = str(df[col].dtype)
        before_kb = df[col].memory_usage(deep=True) / 1024
        df[col] = pd.to_numeric(df[col], downcast="integer")
        after_kb = df[col].memory_usage(deep=True) / 1024
        col_log.append((col, before_dtype, str(df[col].dtype), before_kb - after_kb))

    # ── 2. Float downcasting ─────────────────────────────────────────────────
    # float64 → float32 halves the per-element storage (8 bytes → 4 bytes).
    # float32 range: ±3.4e38, precision: ~7 decimal digits.
    # Sufficient for BRL prices (max ~R$7,000) and weights (max ~40,000 g).
    # review_score (1.0–5.0) loses no meaningful precision at float32.
    for col in float_cols or []:
        before_dtype = str(df[col].dtype)
        before_kb = df[col].memory_usage(deep=True) / 1024
        df[col] = pd.to_numeric(df[col], downcast="float")
        after_kb = df[col].memory_usage(deep=True) / 1024
        col_log.append((col, before_dtype, str(df[col].dtype), before_kb - after_kb))

    # ── 3. Categorical encoding ───────────────────────────────────────────────
    # Converts repeated string objects into a compact integer index + lookup
    # table. For 27 Brazilian states across 110k rows, this collapses ~110k
    # Python string objects into 27 unique strings + an int8 index array.
    for col in categorical_cols or []:
        before_dtype = str(df[col].dtype)
        before_kb = df[col].memory_usage(deep=True) / 1024
        df[col] = df[col].astype("category")
        after_kb = df[col].memory_usage(deep=True) / 1024
        col_log.append((col, before_dtype, str(df[col].dtype), before_kb - after_kb))

    optimized_memory = df.memory_usage(deep=True).sum() / (1024**2)
    total_saved = initial_memory - optimized_memory
    reduction_pct = (total_saved / initial_memory) * 100 if initial_memory > 0 else 0

    # ── Enterprise System Readout ─────────────────────────────────────────────
    print("=" * 70)
    print("🧠  MEMORYOPS: FULL DOWNCASTING & OPTIMIZATION LOG")
    print("=" * 70)
    print(f"{'Column':<30} {'Before':>14} {'After':>14} {'Saved (KB)':>12}")
    print("-" * 70)
    for col, before, after, saved_kb in col_log:
        print(f"  {col:<28} {before:>14} {after:>14} {saved_kb:>11.1f}")
    print("-" * 70)
    print(
        f"  {'TOTAL'::<28} {initial_memory:>13.2f}MB {optimized_memory:>13.2f}MB",
        end="",
    )
    print(f" {total_saved * 1024:>10.1f}")
    print("=" * 70)
    print(f"📊 Initial size  : {initial_memory:.2f} MB")
    print(f"🚀 Optimized size: {optimized_memory:.2f} MB")
    print(f"💾 RAM saved     : {total_saved:.2f} MB  ({reduction_pct:.1f}% reduction)")
    print("✅ Status        : Ready for vectorized aggregations")
    print("=" * 70)

    return df


# ── Q1 Analysis Helpers ───────────────────────────────────────────────────────


def compute_delay_profile(df: pd.DataFrame) -> dict[str, float]:
    """Compute univariate summary statistics for delivery delay severity.

    Designed for BQ1 Q1: quantifies *how bad* delays are and *how much*
    revenue is at risk. Percentile statistics are computed on the **delayed
    population only** (``delivery_delay_days > 0``), while the delay rate and
    revenue exposure are expressed relative to the full valid population.

    Args:
        df: Validated, quality-gated OBT DataFrame with
            ``delivery_delay_days``, ``price``, and ``freight_value`` columns
            already present. Must already be filtered to
            ``is_valid_logistics == 1 and is_valid_product == 1``.

    Returns:
        Dictionary of KPI values:

        - ``total_orders``: row count of the input DataFrame.
        - ``delayed_orders``: count of orders with delay > 0 days.
        - ``delay_rate_pct``: % of all valid orders that were delivered late.
        - ``mean_delay``: mean delay (days) across late orders.
        - ``median_delay``: median delay (days) across late orders.
        - ``p75_delay``, ``p90_delay``, ``p95_delay``: tail-risk percentiles.
        - ``max_delay``: worst single-order delay observed.
        - ``delayed_revenue``: total R$ tied up in late shipments.
        - ``total_revenue``: total R$ across all valid orders.
        - ``rev_at_risk_pct``: ``delayed_revenue / total_revenue * 100``.

    Raises:
        ValueError: If ``delivery_delay_days``, ``price``, or
            ``freight_value`` are missing from ``df``.
    """
    required = {"delivery_delay_days", "price", "freight_value"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"Missing required columns: {missing_cols}. "
            "Derive delivery_delay_days before calling this function."
        )

    delayed_mask = df["delivery_delay_days"] > 0
    delayed_days = df.loc[delayed_mask, "delivery_delay_days"]
    total_revenue = float((df["price"] + df["freight_value"]).sum())
    delayed_revenue = float(
        df.loc[delayed_mask, ["price", "freight_value"]].sum().sum()
    )

    return {
        "total_orders": len(df),
        "delayed_orders": int(delayed_mask.sum()),
        "delay_rate_pct": float(delayed_mask.mean() * 100),
        "mean_delay": float(delayed_days.mean()),
        "median_delay": float(delayed_days.median()),
        "p75_delay": float(delayed_days.quantile(0.75)),
        "p90_delay": float(delayed_days.quantile(0.90)),
        "p95_delay": float(delayed_days.quantile(0.95)),
        "max_delay": float(delayed_days.max()),
        "delayed_revenue": delayed_revenue,
        "total_revenue": total_revenue,
        "rev_at_risk_pct": float(delayed_revenue / total_revenue * 100),
    }


def plot_delay_histogram(
    df: pd.DataFrame,
    ax: matplotlib.axes.Axes,
    max_days: int = 60,
) -> None:
    """Plot the distribution of delivery delay days for late orders only.

    Renders a histogram of ``delivery_delay_days`` clipped at ``max_days``
    to prevent the long tail from compressing the main distribution. Overlays
    p50, p90, and p95 vertical reference lines so executives can read the
    "blast radius" at a glance.

    Args:
        df: Validated, quality-gated OBT DataFrame with a
            ``delivery_delay_days`` column. Must already be filtered to
            valid logistics and product records.
        ax: Matplotlib ``Axes`` object to draw onto. Caller is responsible
            for creating the figure and saving/showing it.
        max_days: Upper clip boundary (default 60). Orders delayed beyond
            this threshold are included in the final bin rather than dropped,
            preserving the true n for the title.

    Returns:
        None. Mutates ``ax`` in place.

    Raises:
        ValueError: If ``delivery_delay_days`` is missing from ``df``.
    """
    if "delivery_delay_days" not in df.columns:
        raise ValueError(
            "Column 'delivery_delay_days' not found. "
            "Derive it before calling plot_delay_histogram()."
        )

    delayed_days = df.loc[df["delivery_delay_days"] > 0, "delivery_delay_days"]
    clipped = delayed_days.clip(upper=max_days)

    sns.histplot(
        clipped,
        bins=40,
        ax=ax,
        color="#e05c5c",
        edgecolor="white",
        linewidth=0.4,
    )

    # Percentile reference lines — p50 tells the typical victim,
    # p90/p95 expose the tail risk that drives 1-star reviews.
    percentile_lines = [
        ("median (p50)", 0.50, "#2196F3"),
        ("p90", 0.90, "#FF9800"),
        ("p95", 0.95, "#C62828"),
    ]
    for label, q, color in percentile_lines:
        val = float(delayed_days.quantile(q))
        ax.axvline(
            val,
            color=color,
            linestyle="--",
            linewidth=1.5,
            label=f"{label} = {val:.0f} days",
        )

    ax.set_title(
        f"Delivery Delay Distribution — Late Orders Only  (n = {len(delayed_days):,})",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Days Late (clipped at 60 for readability)")
    ax.set_ylabel("Number of Orders")
    ax.legend(frameon=False, fontsize=10)


def plot_revenue_at_risk_by_state(
    state_kpis: pd.DataFrame,
    ax: matplotlib.axes.Axes,
    top_n: int = 10,
) -> None:
    """Plot a horizontal bar chart of revenue at risk by customer state.

    Visualises the bivariate relationship between geography and financial
    exposure. Bars are sorted ascending so the worst state appears at the top
    of the chart — the natural reading direction on a horizontal layout.

    Args:
        state_kpis: DataFrame with at minimum ``customer_state`` and
            ``revenue_at_risk`` columns, already sorted descending by
            ``revenue_at_risk`` (as returned by the Q1 aggregation cell).
        ax: Matplotlib ``Axes`` object to draw onto.
        top_n: Number of states to display (default 10). Slices the top rows
            from ``state_kpis`` before sorting ascending for the chart.

    Returns:
        None. Mutates ``ax`` in place.

    Raises:
        ValueError: If ``customer_state`` or ``revenue_at_risk`` are missing
            from ``state_kpis``.
    """
    required = {"customer_state", "revenue_at_risk"}
    missing_cols = required - set(state_kpis.columns)
    if missing_cols:
        raise ValueError(f"Missing columns in state_kpis: {missing_cols}")

    # head(top_n) takes the worst states; sort ascending so worst is at top.
    # .astype(str) strips any category dtype that would retain all 27 state
    # labels and force seaborn to render empty bars for unused categories.
    plot_data = (
        state_kpis.head(top_n)
        .sort_values("revenue_at_risk", ascending=True)
        .assign(customer_state=lambda d: d["customer_state"].astype(str))
    )

    sns.barplot(
        data=plot_data,
        y="customer_state",
        x="revenue_at_risk",
        hue="customer_state",
        legend=False,
        ax=ax,
        palette="flare",
        orient="h",
    )

    # Annotate each bar with the R$ value — eliminates the need to read the axis
    for bar, val in zip(ax.patches, plot_data["revenue_at_risk"]):
        ax.text(
            bar.get_width() * 1.005,
            bar.get_y() + bar.get_height() / 2,
            f"R$ {val:,.0f}",
            va="center",
            ha="left",
            fontsize=9,
        )

    ax.set_title(
        f"Top {top_n} States by Revenue at Risk — Delayed Orders Only",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Revenue at Risk (R$)")
    ax.set_ylabel("Customer State")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"R$ {x:,.0f}"))


# ── Q2 Analysis Helpers ───────────────────────────────────────────────────────
# Scope: SP and RJ only — the two states proven in Q1 to hold 48% of the
# R$ 1.13M revenue-at-risk exposure. All Q2 functions operate strictly on
# this population. Introducing other states would dilute the causal signal
# and resurrect the Amazonas small-sample-size noise that Q1 already debunked.

_Q2_STATES: list[str] = ["SP", "RJ"]


def compute_sp_rj_delay_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a head-to-head delay performance KPI table for SP vs. RJ.

    Establishes *whether* a meaningful performance gap exists between the two
    crisis states before introducing the weight hypothesis. If SP and RJ
    perform identically, there is no differential to explain.

    The comparison uses **all valid orders** (not just delayed ones) as the
    denominator for OTDR, but computes mean/p90 delay statistics on the
    delayed sub-population only — consistent with the Q1 methodology.

    Args:
        df: Quality-gated OBT DataFrame (``is_valid_logistics == 1 AND
            is_valid_product == 1``) with ``customer_state``,
            ``delivery_delay_days``, ``price``, and ``freight_value``
            columns present.

    Returns:
        DataFrame with one row per state (SP, RJ) and columns:

        - ``state``: two-letter state code.
        - ``total_orders``: all valid orders in the state.
        - ``delayed_orders``: orders where ``delivery_delay_days > 0``.
        - ``otdr_pct``: on-time delivery rate (%).
        - ``mean_delay_days``: mean delay across late orders only.
        - ``p90_delay_days``: 90th-percentile delay (late orders only).
        - ``revenue_at_risk``: total R$ from delayed order lines.
        - ``rev_share_pct``: each state's share of the R$ 1.13M total (using
          the combined SP+RJ delayed revenue as the denominator).

        Rows ordered SP first, RJ second.

    Raises:
        ValueError: If any required column is absent from ``df``.
    """
    required = {"customer_state", "delivery_delay_days", "price", "freight_value"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    focus = df.loc[df["customer_state"].astype(str).isin(_Q2_STATES)].copy()

    delayed_mask = focus["delivery_delay_days"] > 0

    base = (
        focus.assign(
            is_delayed=delayed_mask.astype("int8"),
            delayed_value=(focus["price"] + focus["freight_value"]) * delayed_mask,
        )
        .groupby("customer_state", observed=True, as_index=False)
        .agg(
            total_orders=("order_id", "count"),
            delayed_orders=("is_delayed", "sum"),
            revenue_at_risk=("delayed_value", "sum"),
        )
        .assign(
            otdr_pct=lambda d: (1 - d["delayed_orders"] / d["total_orders"]) * 100,
        )
        .rename(columns={"customer_state": "state"})
    )

    delayed_stats = (
        focus.loc[delayed_mask]
        .groupby("customer_state", observed=True)["delivery_delay_days"]
        .agg(
            mean_delay_days="mean",
            p90_delay_days=lambda x: x.quantile(0.90),
        )
        .reset_index()
        .rename(columns={"customer_state": "state"})
    )

    merged = base.merge(delayed_stats, on="state", how="left")
    total_combined_risk = merged["revenue_at_risk"].sum()
    merged["rev_share_pct"] = merged["revenue_at_risk"] / total_combined_risk * 100

    # Pin row order: SP first, RJ second
    merged["state"] = pd.Categorical(
        merged["state"].astype(str),
        categories=_Q2_STATES,
        ordered=True,
    )
    return merged.sort_values("state").reset_index(drop=True)


def plot_sp_rj_comparison(
    comparison_df: pd.DataFrame,
    axes: tuple[matplotlib.axes.Axes, matplotlib.axes.Axes, matplotlib.axes.Axes],
) -> None:
    """Side-by-side grouped bar charts comparing SP vs. RJ on three KPIs.

    Renders three panels on pre-created ``Axes`` objects:

    1. **OTDR %** — with a dashed 95% SLA reference line.
    2. **Mean Delay Days** (delayed orders only).
    3. **Revenue at Risk (R$)**.

    This layout lets an executive read all three dimensions at once without
    flipping between charts. SP and RJ bars are colour-coded consistently
    across all panels (blue = SP, red = RJ).

    Args:
        comparison_df: DataFrame returned by
            ``compute_sp_rj_delay_comparison``, with ``state``, ``otdr_pct``,
            ``mean_delay_days``, and ``revenue_at_risk`` columns.
        axes: Tuple of exactly 3 Matplotlib ``Axes`` objects — one per panel.
            Caller is responsible for creating the figure.

    Returns:
        None. Mutates all three ``Axes`` in place.

    Raises:
        ValueError: If required columns are absent or ``axes`` has != 3 items.
    """
    required = {"state", "otdr_pct", "mean_delay_days", "revenue_at_risk"}
    if missing := required - set(comparison_df.columns):
        raise ValueError(f"Missing columns: {missing}")
    if len(axes) != 3:
        raise ValueError("axes must be a tuple of exactly 3 Axes objects.")

    palette = {"SP": "#1565C0", "RJ": "#B71C1C"}
    plot_data = comparison_df.assign(state=lambda d: d["state"].astype(str))

    ax_otdr, ax_delay, ax_rev = axes

    # ── Panel 1: OTDR % ──────────────────────────────────────────────────────
    sns.barplot(
        data=plot_data,
        x="state",
        y="otdr_pct",
        hue="state",
        palette=palette,
        legend=False,
        ax=ax_otdr,
    )
    ax_otdr.axhline(
        95.0, color="#FF6F00", linestyle="--", linewidth=1.5, label="95% SLA"
    )
    for bar, val in zip(ax_otdr.patches, plot_data["otdr_pct"]):
        ax_otdr.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )
    ax_otdr.set_ylim(bottom=plot_data["otdr_pct"].min() - 5, top=100)
    ax_otdr.set_title("On-Time Delivery Rate (%)", fontsize=12, pad=10)
    ax_otdr.set_xlabel("")
    ax_otdr.set_ylabel("OTDR %")
    ax_otdr.legend(frameon=False, fontsize=9)

    # ── Panel 2: Mean Delay ──────────────────────────────────────────────────
    sns.barplot(
        data=plot_data,
        x="state",
        y="mean_delay_days",
        hue="state",
        palette=palette,
        legend=False,
        ax=ax_delay,
    )
    for bar, val in zip(ax_delay.patches, plot_data["mean_delay_days"]):
        ax_delay.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"{val:.1f}d",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )
    ax_delay.set_title("Mean Delay — Late Orders Only (days)", fontsize=12, pad=10)
    ax_delay.set_xlabel("")
    ax_delay.set_ylabel("Mean Delay (days)")

    # ── Panel 3: Revenue at Risk ─────────────────────────────────────────────
    sns.barplot(
        data=plot_data,
        x="state",
        y="revenue_at_risk",
        hue="state",
        palette=palette,
        legend=False,
        ax=ax_rev,
    )
    for bar, val in zip(ax_rev.patches, plot_data["revenue_at_risk"]):
        ax_rev.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() * 1.01,
            f"R$ {val:,.0f}",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )
    ax_rev.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"R$ {x / 1_000:.0f}k")
    )
    ax_rev.set_title("Revenue at Risk (R$)", fontsize=12, pad=10)
    ax_rev.set_xlabel("")
    ax_rev.set_ylabel("Revenue at Risk (R$)")


def compute_weight_delay_correlation(df: pd.DataFrame) -> dict[str, float | int]:
    """Compute Pearson and Spearman correlations between weight and delay.

    Tests whether ``product_weight_g`` has a statistically meaningful linear
    or monotonic relationship with ``delivery_delay_days``.

    Both metrics are filtered to ``product_weight_g > 0`` (zero-weight records
    are corrupted catalog entries) and ``delivery_delay_days > 0`` (on-time
    and early orders are not part of the delay-weight relationship).

    Args:
        df: Quality-gated OBT DataFrame with ``product_weight_g`` and
            ``delivery_delay_days`` columns present. For Q2, pass the
            **SP+RJ subset only** to keep the analysis scoped to the
            R$ 1.13M crisis population identified in Q1.

    Returns:
        Dictionary of correlation statistics:

        - ``n_orders``: sample size used (weight > 0 AND delay > 0).
        - ``pearson_r``: Pearson product-moment correlation coefficient.
        - ``pearson_p``: two-sided p-value for Pearson r.
        - ``spearman_r``: Spearman rank correlation coefficient.
        - ``spearman_p``: two-sided p-value for Spearman r.
        - ``weight_p25``, ``weight_p50``, ``weight_p75``, ``weight_p90``,
          ``weight_p95``, ``weight_max``: weight distribution percentiles (g).
        - ``mean_delay_q1``: mean delay for lightest-weight quartile (Q1).
        - ``mean_delay_q4``: mean delay for heaviest-weight quartile (Q4).
        - ``delay_uplift_pct``: ``(mean_delay_q4 / mean_delay_q1 - 1) * 100``.
          Positive → heavier packages arrive later on average.

    Raises:
        ValueError: If ``product_weight_g`` or ``delivery_delay_days`` are
            missing from ``df``.
    """
    required = {"product_weight_g", "delivery_delay_days"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    analysis_df = df.loc[
        (df["product_weight_g"] > 0) & (df["delivery_delay_days"] > 0),
        ["product_weight_g", "delivery_delay_days"],
    ].dropna()

    weight = analysis_df["product_weight_g"].astype(float).to_numpy()
    delay = analysis_df["delivery_delay_days"].astype(float).to_numpy()

    pearson_r, pearson_p = stats.pearsonr(weight, delay)
    spearman_r, spearman_p = stats.spearmanr(weight, delay)

    weight_series = analysis_df["product_weight_g"].astype(float)
    quartile_labels = pd.qcut(weight_series, q=4, labels=["Q1", "Q2", "Q3", "Q4"])
    quartile_mean_delay = (
        analysis_df["delivery_delay_days"].astype(float).groupby(quartile_labels).mean()
    )
    mean_q1 = float(quartile_mean_delay.get("Q1", float("nan")))
    mean_q4 = float(quartile_mean_delay.get("Q4", float("nan")))

    return {
        "n_orders": len(analysis_df),
        "pearson_r": float(pearson_r),
        "pearson_p": float(pearson_p),
        "spearman_r": float(spearman_r),
        "spearman_p": float(spearman_p),
        "weight_p25": float(weight_series.quantile(0.25)),
        "weight_p50": float(weight_series.quantile(0.50)),
        "weight_p75": float(weight_series.quantile(0.75)),
        "weight_p90": float(weight_series.quantile(0.90)),
        "weight_p95": float(weight_series.quantile(0.95)),
        "weight_max": float(weight_series.max()),
        "mean_delay_q1": mean_q1,
        "mean_delay_q4": mean_q4,
        "delay_uplift_pct": float((mean_q4 / mean_q1 - 1) * 100)
        if mean_q1 > 0
        else float("nan"),
    }


def plot_weight_scatter_sp_rj(
    df: pd.DataFrame,
    ax: matplotlib.axes.Axes,
    weight_cap_g: int = 20_000,
) -> None:
    """Scatter of weight vs. delay for SP and RJ with per-state OLS lines.

    Renders two overlapping ``sns.regplot`` layers — one per state — using
    distinct colours. Separate regression lines make it immediately visible
    whether the weight-delay slope differs between SP and RJ. A common slope
    rules out weight as the explanation for RJ's worse OTDR; diverging slopes
    would confirm it.

    Args:
        df: Quality-gated OBT DataFrame pre-filtered to SP+RJ
            (``customer_state.isin(["SP","RJ"])``). Must contain
            ``product_weight_g``, ``delivery_delay_days``, and
            ``customer_state``.
        ax: Matplotlib ``Axes`` to draw onto.
        weight_cap_g: Upper clip (default 20,000 g). Rows above this are
            excluded from both the scatter and regression visually.

    Returns:
        None. Mutates ``ax`` in place.

    Raises:
        ValueError: If required columns are absent from ``df``.
    """
    required = {"product_weight_g", "delivery_delay_days", "customer_state"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    base = (
        df.loc[
            (df["product_weight_g"] > 0) & (df["delivery_delay_days"] > 0),
            ["customer_state", "product_weight_g", "delivery_delay_days"],
        ]
        .dropna()
        .query(f"product_weight_g <= {weight_cap_g}")
        .assign(
            customer_state=lambda d: d["customer_state"].astype(str),
            product_weight_g=lambda d: d["product_weight_g"].astype(float),
            delivery_delay_days=lambda d: d["delivery_delay_days"].astype(float),
        )
    )

    palette = {"SP": "#1565C0", "RJ": "#B71C1C"}
    for state, color in palette.items():
        subset = base.loc[base["customer_state"] == state]
        sns.regplot(
            data=subset,
            x="product_weight_g",
            y="delivery_delay_days",
            ax=ax,
            scatter_kws={"alpha": 0.18, "s": 10, "color": color, "label": state},
            line_kws={"color": color, "linewidth": 2, "label": f"{state} trend"},
            ci=95,
        )

    # Build a clean legend: one dot + one line entry per state
    handles, labels = ax.get_legend_handles_labels()
    # regplot creates 2 handles per call (scatter + line), keep unique labels
    seen: set[str] = set()
    unique_handles = []
    unique_labels = []
    for h, lbl in zip(handles, labels):
        if lbl not in seen:
            seen.add(lbl)
            unique_handles.append(h)
            unique_labels.append(lbl)
    ax.legend(unique_handles, unique_labels, frameon=False, fontsize=10)

    ax.set_title(
        f"Product Weight vs. Delivery Delay — SP vs. RJ  "
        f"(capped at {weight_cap_g // 1000} kg · "
        f"n = {len(base):,})",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Product Weight (g)")
    ax.set_ylabel("Delivery Delay (days)")


def plot_weight_quartile_by_state(
    df: pd.DataFrame,
    ax: matplotlib.axes.Axes,
) -> None:
    """Grouped bar chart: mean delay by weight quartile × state (SP vs. RJ).

    The multivariate interaction test for Q2: if the Q4-heavy bars are
    proportionally *much taller* in RJ than in SP, package weight is
    amplifying RJ's specific disadvantage. If both states show the same
    Q1→Q4 gradient, weight is a uniform additive factor and geography
    (last-mile complexity, hub distance) is the primary differentiator.

    **Interpretation guide:**
    - Q4 − Q1 gap **larger in RJ** → weight × geography interaction confirmed
      → RJ couriers struggle disproportionately with heavy parcels.
    - Q4 − Q1 gap **same in both states** → weight is additive but uniform;
      geography independently explains RJ's worse OTDR.
    - All bars for RJ **uniformly higher** than SP at each quartile →
      geography dominates; weight is irrelevant to the SP/RJ gap.

    Args:
        df: Quality-gated OBT DataFrame pre-filtered to SP+RJ. Must contain
            ``customer_state``, ``product_weight_g``, and
            ``delivery_delay_days``.
        ax: Matplotlib ``Axes`` to draw onto.

    Returns:
        None. Mutates ``ax`` in place.

    Raises:
        ValueError: If required columns are absent from ``df``.
    """
    required = {"customer_state", "product_weight_g", "delivery_delay_days"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    analysis_df = (
        df.loc[
            (df["product_weight_g"] > 0) & (df["delivery_delay_days"] > 0),
            ["customer_state", "product_weight_g", "delivery_delay_days"],
        ]
        .dropna()
        .assign(
            customer_state=lambda d: d["customer_state"].astype(str),
            product_weight_g=lambda d: d["product_weight_g"].astype(float),
            delivery_delay_days=lambda d: d["delivery_delay_days"].astype(float),
        )
    )

    analysis_df["weight_quartile"] = pd.qcut(
        analysis_df["product_weight_g"],
        q=4,
        labels=["Q1 · Light", "Q2", "Q3", "Q4 · Heavy"],
    ).astype(str)

    grouped = (
        analysis_df.groupby(
            ["customer_state", "weight_quartile"], observed=True, as_index=False
        )["delivery_delay_days"]
        .mean()
        .rename(columns={"delivery_delay_days": "mean_delay_days"})
    )

    sns.barplot(
        data=grouped,
        x="weight_quartile",
        y="mean_delay_days",
        hue="customer_state",
        palette={"SP": "#1565C0", "RJ": "#B71C1C"},
        ax=ax,
        order=["Q1 · Light", "Q2", "Q3", "Q4 · Heavy"],
    )

    ax.set_title(
        "Mean Delay by Weight Quartile × State — SP vs. RJ  "
        "(Multivariate Interaction Test)",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Weight Quartile  (Q1 = lightest 25%  →  Q4 = heaviest 25%)")
    ax.set_ylabel("Mean Delay (days, late orders only)")
    ax.legend(title="State", frameon=False, fontsize=10, title_fontsize=10)


# ── Q3 Analysis Helpers ───────────────────────────────────────────────────────

# Delay bins used consistently across Q3 charts and tables.
_Q3_BINS: list[float] = [float("-inf"), 0, 3, 7, 14, 21, 30, float("inf")]
_Q3_LABELS: list[str] = [
    "On-Time (≤0d)",
    "Late 1–3d",
    "Late 4–7d",
    "Late 8–14d",
    "Late 15–21d",
    "Late 22–30d",
    "Late 31+d",
]


def compute_review_threshold(df: pd.DataFrame) -> pd.DataFrame:
    """Compute review-score metrics by delivery-delay bin.

    Bins all orders (on-time and late) into seven delay brackets and
    calculates, per bracket:

    - ``n_orders``     — total order count
    - ``n_reviewed``   — orders where ``review_score`` is not NaN
    - ``n_1star``      — orders with ``review_score == 1``
    - ``n_silent``     — delayed orders with no review (``review_score`` is NaN)
    - ``mean_score``   — mean review score (NaN-safe; on reviewed orders only)
    - ``pct_1star``    — percentage of reviewed orders that are 1-star
    - ``pct_silent``   — percentage of orders with no review
    - ``pct_reviewed`` — percentage of orders that have a review

    Args:
        df: Quality-gated OBT DataFrame (``is_valid_logistics == 1`` and
            ``is_valid_product == 1``) containing ``delivery_delay_days``
            and ``review_score`` columns.

    Returns:
        DataFrame with one row per delay bin, ordered from on-time to
        most-severe-late.  Columns: ``delay_bin``, ``n_orders``,
        ``n_reviewed``, ``n_1star``, ``n_silent``, ``mean_score``,
        ``pct_1star``, ``pct_silent``, ``pct_reviewed``.

    Raises:
        ValueError: If ``delivery_delay_days`` or ``review_score`` columns
            are absent from ``df``.
    """
    required = {"delivery_delay_days", "review_score"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    work = df[["delivery_delay_days", "review_score"]].copy()
    work["delay_bin"] = pd.cut(
        work["delivery_delay_days"].astype(float),
        bins=_Q3_BINS,
        labels=_Q3_LABELS,
        right=True,
    )

    agg = (
        work.groupby("delay_bin", observed=True)
        .agg(
            n_orders=("delivery_delay_days", "count"),
            n_reviewed=("review_score", "count"),
            mean_score=("review_score", "mean"),
            n_1star=(
                "review_score",
                lambda s: (s.astype(float) == 1.0).sum(),
            ),
        )
        .reset_index()
    )

    agg["n_silent"] = agg["n_orders"] - agg["n_reviewed"]
    agg["pct_reviewed"] = (agg["n_reviewed"] / agg["n_orders"] * 100).round(1)
    agg["pct_1star"] = (agg["n_1star"] / agg["n_reviewed"] * 100).round(1)
    agg["pct_silent"] = (agg["n_silent"] / agg["n_orders"] * 100).round(1)
    agg["mean_score"] = agg["mean_score"].round(2)

    return agg


def plot_review_score_threshold(
    threshold_df: pd.DataFrame,
    ax: plt.Axes,
) -> None:
    """Plot mean review score and % 1-star reviews by delivery-delay bin.

    Renders a dual-signal chart on a single axis:

    - Blue line + markers: mean review score per delay bin (left y-axis)
    - Orange bars (semi-transparent): % 1-star reviews per bin (right y-axis)
    - Horizontal dashed reference line at score = 2.0 (1-star danger zone)
    - Horizontal dashed reference line at score = 4.0 (healthy baseline)
    - Text annotation marking the first bin where mean score drops below 2.5

    Args:
        threshold_df: Output of :func:`compute_review_threshold`.
        ax: Matplotlib ``Axes`` object on which to draw the primary (score)
            series.  A secondary y-axis is created internally via ``twinx()``.

    Returns:
        None.  The chart is rendered onto ``ax`` in place.

    Raises:
        ValueError: If required columns are absent from ``threshold_df``.
    """
    required = {"delay_bin", "mean_score", "pct_1star"}
    if missing := required - set(threshold_df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    labels = threshold_df["delay_bin"].astype(str).tolist()
    x = range(len(labels))

    ax2 = ax.twinx()

    # ── Bars: % 1-star (right axis) ──────────────────────────────────────────
    ax2.bar(
        x,
        threshold_df["pct_1star"],
        color="#FF8F00",
        alpha=0.30,
        width=0.55,
        label="% 1-Star Reviews",
        zorder=2,
    )
    ax2.set_ylabel(
        "% 1-Star Reviews (of reviewed orders)", fontsize=11, color="#E65100"
    )
    ax2.tick_params(axis="y", colors="#E65100")
    ax2.set_ylim(0, threshold_df["pct_1star"].max() * 1.5 + 5)

    # ── Line: mean review score (left axis) ──────────────────────────────────
    ax.plot(
        list(x),
        threshold_df["mean_score"],
        color="#1565C0",
        linewidth=2.5,
        marker="o",
        markersize=8,
        zorder=5,
        label="Mean Review Score",
    )

    # Annotate score values on the line
    for xi, score in zip(x, threshold_df["mean_score"]):
        if not pd.isna(score):
            ax.annotate(
                f"{score:.2f}",
                xy=(xi, score),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color="#1565C0",
                fontweight="bold",
            )

    # ── Reference lines ───────────────────────────────────────────────────────
    ax.axhline(
        4.0,
        color="#2E7D32",
        linestyle="--",
        linewidth=1.2,
        alpha=0.8,
        label="Healthy Baseline (4.0)",
    )
    ax.axhline(
        2.5,
        color="#B71C1C",
        linestyle="--",
        linewidth=1.2,
        alpha=0.8,
        label="1-Star Danger Zone (≤ 2.5)",
    )
    ax.axhspan(1.0, 2.5, alpha=0.06, color="#B71C1C", zorder=1)

    # ── Axes formatting ───────────────────────────────────────────────────────
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=10)
    ax.set_ylim(1.0, 5.4)
    ax.set_ylabel("Mean Review Score (1–5 stars)", fontsize=11, color="#1565C0")
    ax.tick_params(axis="y", colors="#1565C0")
    ax.set_xlabel("Delivery Delay Bracket", fontsize=11)
    ax.set_title(
        "Review Score Collapse by Delay Severity\n"
        "— Identifying the 1-Star Blast Radius Threshold",
        fontsize=13,
        pad=12,
    )

    # Combined legend
    handles_l, labels_l = ax.get_legend_handles_labels()
    handles_r, labels_r = ax2.get_legend_handles_labels()
    ax.legend(
        handles_l + handles_r,
        labels_l + labels_r,
        loc="lower left",
        frameon=True,
        fontsize=9,
    )


def plot_silent_detractor_breakdown(
    df: pd.DataFrame,
    ax: plt.Axes,
) -> None:
    """Plot the Silent Detractor breakdown as a stacked 100% bar chart.

    For every delivery-delay bin, shows what fraction of customers:

    - Gave a **1-star** review (vocal, measurable brand damage)
    - Gave a **2–5-star** review (satisfied or mildly disappointed)
    - Left **no review** — the "Silent Detractors" (invisible churn risk)

    The stacked proportion format makes it obvious that as delay grows,
    the silent segment first grows (customers disengage) and then the
    1-star segment also grows (customers are angry enough to act).

    Args:
        df: Quality-gated OBT DataFrame containing ``delivery_delay_days``
            and ``review_score`` columns, already including
            ``is_valid_logistics == 1`` and ``is_valid_product == 1``
            filters.
        ax: Matplotlib ``Axes`` object on which to draw.

    Returns:
        None.  The chart is rendered onto ``ax`` in place.

    Raises:
        ValueError: If required columns are absent from ``df``.
    """
    required = {"delivery_delay_days", "review_score"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    work = df[["delivery_delay_days", "review_score"]].copy()
    work["delay_bin"] = pd.cut(
        work["delivery_delay_days"].astype(float),
        bins=_Q3_BINS,
        labels=_Q3_LABELS,
        right=True,
    )

    # Vectorised segment classification (no .apply())
    score_f = work["review_score"].astype(float)
    work["segment"] = pd.NA
    work.loc[score_f.isna(), "segment"] = "Silent (No Review)"
    work.loc[score_f == 1.0, "segment"] = "1-Star (Vocal Detractor)"
    work.loc[score_f > 1.0, "segment"] = "2–5 Star (Retained/Mild)"

    pivot = (
        work.groupby(["delay_bin", "segment"], observed=True)
        .size()
        .unstack(fill_value=0)
    )

    segment_order = [
        "2–5 Star (Retained/Mild)",
        "Silent (No Review)",
        "1-Star (Vocal Detractor)",
    ]
    pivot = pivot.reindex(columns=segment_order, fill_value=0)

    # Convert to percentages
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100

    palette = {
        "2–5 Star (Retained/Mild)": "#43A047",
        "Silent (No Review)": "#9E9E9E",
        "1-Star (Vocal Detractor)": "#E53935",
    }

    bottom = pd.Series([0.0] * len(pivot_pct), index=pivot_pct.index, dtype=float)
    labels = pivot_pct.index.astype(str).tolist()
    x = list(range(len(labels)))

    for segment in segment_order:
        values = pivot_pct[segment].values
        ax.bar(
            x,
            values,
            bottom=bottom.values,
            label=segment,
            color=palette[segment],
            width=0.6,
            edgecolor="white",
            linewidth=0.6,
        )
        # Annotate segments ≥ 8% for readability
        for xi, val, bot in zip(x, values, bottom.values):
            if val >= 8:
                ax.text(
                    xi,
                    bot + val / 2,
                    f"{val:.0f}%",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white",
                    fontweight="bold",
                )
        bottom = bottom + pd.Series(values, index=pivot_pct.index, dtype=float)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=10)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Share of Orders (%)", fontsize=11)
    ax.set_xlabel("Delivery Delay Bracket", fontsize=11)
    ax.set_title(
        "Silent Detractor Breakdown by Delay Severity\n"
        "— Proportion of 1-Star, Satisfied & Silent Customers",
        fontsize=13,
        pad=12,
    )
    ax.legend(
        loc="upper right",
        frameon=True,
        fontsize=9,
        title="Customer Segment",
        title_fontsize=9,
    )


# ── Q4 Analysis Helpers ───────────────────────────────────────────────────────

# SLA red line inherited from Q3 threshold analysis.
# Any order delayed beyond this threshold is in the 1-star blast zone.
_Q4_BLAST_THRESHOLD: int = 14

# Cohort labels used consistently across Q4 functions and notebook cells.
_Q4_COHORT_ONTIME = "A · On-Time (≤0d)"
_Q4_COHORT_RECOVERABLE = "B · Late-Recoverable (1–14d)"
_Q4_COHORT_BLAST = "C · Blast-Zone (15+d)"
_Q4_COHORT_ORDER = [_Q4_COHORT_ONTIME, _Q4_COHORT_RECOVERABLE, _Q4_COHORT_BLAST]


def compute_rpr_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Repeat Purchase Rate and CLV proxy metrics by delivery cohort.

    Assigns every unique customer to one of three cohorts based on their
    **worst** delivery experience (the most delayed order they ever received):

    - **Cohort A** — On-Time (delay ≤ 0 on all orders)
    - **Cohort B** — Late-Recoverable (worst delay 1–14 days)
    - **Cohort C** — Blast-Zone (worst delay > 14 days, the Q3 SLA red line)

    Then computes per-cohort:

    - ``n_customers``         — unique customer count
    - ``n_repeat``            — customers with > 1 unique order
    - ``rpr_pct``             — Repeat Purchase Rate (%)
    - ``mean_orders``         — mean order count per customer (all customers)
    - ``mean_orders_repeater``— mean order count among repeat buyers only
    - ``total_revenue``       — total price + freight across all orders
    - ``rev_per_customer``    — total revenue divided by unique customer count
    - ``rev_per_repeater``    — total revenue divided by repeat buyer count

    Args:
        df: Quality-gated OBT DataFrame (``is_valid_logistics == 1`` and
            ``is_valid_product == 1``) containing ``delivery_delay_days``,
            ``customer_unique_id``, ``order_id``, ``price``, and
            ``freight_value`` columns.

    Returns:
        DataFrame with one row per cohort (3 rows), ordered A → B → C.
        Columns: ``cohort``, ``n_customers``, ``n_repeat``, ``rpr_pct``,
        ``mean_orders``, ``mean_orders_repeater``, ``total_revenue``,
        ``rev_per_customer``, ``rev_per_repeater``.

    Raises:
        ValueError: If required columns are absent from ``df``.
    """
    required = {
        "delivery_delay_days",
        "customer_unique_id",
        "order_id",
        "price",
        "freight_value",
    }
    if missing := required - set(df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    work = df[
        [
            "customer_unique_id",
            "order_id",
            "delivery_delay_days",
            "price",
            "freight_value",
        ]
    ].copy()
    work["order_value"] = work["price"].astype(float) + work["freight_value"].astype(
        float
    )
    work["delay_days"] = work["delivery_delay_days"].astype(float)

    # ── Per-customer worst delay and total revenue ────────────────────────────
    # Vectorised: groupby + agg in one pass — no apply/iterrows.
    cust = work.groupby("customer_unique_id", as_index=False).agg(
        max_delay=("delay_days", "max"),
        n_orders=("order_id", "nunique"),
        total_rev=("order_value", "sum"),
    )

    # ── Cohort assignment (vectorised boolean indexing) ───────────────────────
    cust["cohort"] = pd.NA
    cust.loc[cust["max_delay"] <= 0, "cohort"] = _Q4_COHORT_ONTIME
    cust.loc[
        (cust["max_delay"] > 0) & (cust["max_delay"] <= _Q4_BLAST_THRESHOLD),
        "cohort",
    ] = _Q4_COHORT_RECOVERABLE
    cust.loc[cust["max_delay"] > _Q4_BLAST_THRESHOLD, "cohort"] = _Q4_COHORT_BLAST

    # ── Aggregate per cohort ──────────────────────────────────────────────────
    cohort_agg = (
        cust.groupby("cohort", as_index=False)
        .agg(
            n_customers=("customer_unique_id", "count"),
            n_repeat=("n_orders", lambda s: (s > 1).sum()),
            mean_orders=("n_orders", "mean"),
            total_revenue=("total_rev", "sum"),
        )
        .assign(
            rpr_pct=lambda d: (d["n_repeat"] / d["n_customers"] * 100).round(2),
            rev_per_customer=lambda d: (d["total_revenue"] / d["n_customers"]).round(2),
        )
    )

    # Repeat-buyer revenue (only customers who bought > 1 time)
    repeater_rev = (
        cust.loc[cust["n_orders"] > 1]
        .groupby("cohort", as_index=False)["total_rev"]
        .mean()
        .rename(columns={"total_rev": "rev_per_repeater"})
    )
    repeater_orders = (
        cust.loc[cust["n_orders"] > 1]
        .groupby("cohort", as_index=False)["n_orders"]
        .mean()
        .rename(columns={"n_orders": "mean_orders_repeater"})
    )

    cohort_agg = cohort_agg.merge(repeater_rev, on="cohort", how="left").merge(
        repeater_orders, on="cohort", how="left"
    )

    # Enforce display order A → B → C
    cohort_agg["cohort"] = pd.Categorical(
        cohort_agg["cohort"], categories=_Q4_COHORT_ORDER, ordered=True
    )
    return cohort_agg.sort_values("cohort").reset_index(drop=True)


def plot_rpr_cohort_comparison(
    cohort_df: pd.DataFrame,
    ax: plt.Axes,
) -> None:
    """Plot Repeat Purchase Rate % as a vertical bar chart by delivery cohort.

    Renders three cohort bars (A=on-time, B=recoverable, C=blast-zone) with:

    - Green / amber / red palette matching severity
    - Percentage annotations above each bar
    - SLA target reference line at 10%
    - Current overall baseline reference line at 3%

    Args:
        cohort_df: Output of :func:`compute_rpr_cohort`.
        ax: Matplotlib ``Axes`` object on which to draw.

    Returns:
        None.  Renders in place.

    Raises:
        ValueError: If required columns are absent from ``cohort_df``.
    """
    required = {"cohort", "rpr_pct"}
    if missing := required - set(cohort_df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    palette = {
        _Q4_COHORT_ONTIME: "#2E7D32",
        _Q4_COHORT_RECOVERABLE: "#F57F17",
        _Q4_COHORT_BLAST: "#B71C1C",
    }
    labels = cohort_df["cohort"].astype(str).tolist()
    values = cohort_df["rpr_pct"].tolist()
    colors = [palette.get(lbl, "#607D8B") for lbl in labels]

    bars = ax.bar(
        labels, values, color=colors, width=0.5, edgecolor="white", linewidth=0.8
    )

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.15,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=12,
            fontweight="bold",
            color="#212121",
        )

    ax.axhline(
        10.0,
        color="#1565C0",
        linestyle="--",
        linewidth=1.4,
        alpha=0.8,
        label="SLA Target (10%)",
    )
    ax.axhline(
        3.0,
        color="#757575",
        linestyle=":",
        linewidth=1.2,
        alpha=0.8,
        label="Current Baseline (3%)",
    )

    ax.set_ylim(0, max(values) * 1.4 + 2)
    ax.set_title(
        "Repeat Purchase Rate by Delivery Cohort\n— The Retention Destruction Ladder",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Delivery Cohort  (A = best experience  →  C = worst)", fontsize=11)
    ax.set_ylabel("Repeat Purchase Rate (%)", fontsize=11)
    ax.legend(frameon=True, fontsize=9)
    ax.tick_params(axis="x", labelsize=9)


def plot_clv_destruction(
    cohort_df: pd.DataFrame,
    ax: plt.Axes,
) -> None:
    """Plot average revenue per customer by delivery cohort as a waterfall-style bar chart.

    Renders three cohort bars showing revenue-per-customer (CLV proxy) with:

    - Absolute R$ annotations on each bar
    - Delta annotations (vs. Cohort A baseline) in a secondary colour
    - Green / amber / red palette consistent with :func:`plot_rpr_cohort_comparison`

    Args:
        cohort_df: Output of :func:`compute_rpr_cohort`.
        ax: Matplotlib ``Axes`` object on which to draw.

    Returns:
        None.  Renders in place.

    Raises:
        ValueError: If required columns are absent from ``cohort_df``.
    """
    required = {"cohort", "rev_per_customer"}
    if missing := required - set(cohort_df.columns):
        raise ValueError(f"Missing required columns: {missing}")

    palette = {
        _Q4_COHORT_ONTIME: "#2E7D32",
        _Q4_COHORT_RECOVERABLE: "#F57F17",
        _Q4_COHORT_BLAST: "#B71C1C",
    }
    labels = cohort_df["cohort"].astype(str).tolist()
    values = cohort_df["rev_per_customer"].astype(float).tolist()
    colors = [palette.get(lbl, "#607D8B") for lbl in labels]
    baseline = values[0]

    bars = ax.bar(
        labels, values, color=colors, width=0.5, edgecolor="white", linewidth=0.8
    )

    for bar, val, lbl in zip(bars, values, labels):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.01,
            f"R$ {val:,.0f}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )
        if lbl != _Q4_COHORT_ONTIME:
            delta = val - baseline
            delta_str = f"Δ R$ {delta:+,.0f}"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() / 2,
                delta_str,
                ha="center",
                va="center",
                fontsize=9,
                color="white",
                fontweight="bold",
            )

    ax.set_ylim(0, max(values) * 1.35)
    ax.set_title(
        "Average Revenue per Customer by Delivery Cohort\n— CLV Destruction Quantified",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Delivery Cohort  (A = best experience  →  C = worst)", fontsize=11)
    ax.set_ylabel("Avg Revenue per Customer (R$)", fontsize=11)
    ax.tick_params(axis="x", labelsize=9)
