# GitHub Copilot Instructions — Olist E-Commerce Logistics Diagnostics

## Project Mission

You are assisting a **Senior Data Analyst** investigating a **critical R$1.2M logistics
bottleneck** for the Olist e-commerce platform. All code must be production-quality,
modular, and immediately runnable inside Jupyter Notebooks or the `src/` library.

---

## Tech Stack

| Layer              | Tool                       | Version         |
| ------------------ | -------------------------- | --------------- |
| Language           | Python                     | ≥ 3.14          |
| Package manager    | uv                         | latest          |
| Linter / Formatter | ruff                       | ≥ 0.15          |
| Data wrangling     | pandas                     | ≥ 3.0           |
| Visualisation      | seaborn + matplotlib       | ≥ 0.13 / ≥ 3.10 |
| Schema validation  | pandera                    | ≥ 0.29          |
| Secrets            | python-dotenv              | ≥ 1.2           |
| Warehouse client   | snowflake-connector-python | ≥ 4.3           |
| Pre-commit hooks   | nbstripout, ruff           | —               |

---

## Folder Structure & Responsibilities

```
ecommerce-logistics-diagnostics/
├── data/
│   ├── raw/                  # obt_cache.parquet lives here — READ ONLY
│   └── processed/            # Outputs from transformations
├── notebooks/
│   └── 01_logistics_root_cause_diagnostics.ipynb
├── src/
│   ├── __init__.py
│   ├── db_connection.py      # Snowflake connection logic ONLY
│   └── diagnostic_utils.py   # Reusable plotting & transform helpers
└── visuals/                  # Exported chart PNGs / SVGs
```

**Rule:** Complex logic (custom plot functions, Snowflake connectors, reusable
transformers) belongs in `src/`. Notebooks are for orchestration and narrative only.
Do NOT put multi-function logic inline inside notebook cells.

---

## Data Architecture

- The data pipeline is a **dbt Medallion Architecture** (Bronze → Silver → Gold).
- All upstream cleaning and joining has already been done. Do NOT write code to clean
  raw data or handle cartesian fan-outs — dbt already solved this.
- The final output is a **One Big Table (OBT)** materialised in Snowflake.
- This repository is the official **dbt Exposure** downstream of that DAG. The data
  flow is strictly one-directional:

  ```
  Snowflake → data/raw/obt_cache.parquet → Notebook → data/processed/
  ```

- For local development, always read the Parquet cache with the PyArrow engine:

```python
df = pd.read_parquet("data/raw/obt_cache.parquet", engine="pyarrow")
```

### FinOps Rule — STRICTLY ENFORCED

> **Never query the live Snowflake database inside notebook cells or analysis scripts.**
> Always read from the local Parquet cache. Snowflake connections are only permitted
> inside `src/db_connection.py` when explicitly refreshing the cache.

---

## Critical Data Quality Flags

Two boolean columns gate every baseline metric. Always filter on them unless the
analysis explicitly requires unfiltered data (and that must be commented):

```python
df_valid = df.query("is_valid_logistics == 1 and is_valid_product == 1")
```

---

## Null Handling Rules

- **`review_score`** — NEVER fill with `0`. NaN means the buyer did not review.
  Filling with 0 corrupts all average calculations.
  Filter dynamically only when the analysis involves review feedback:

  ```python
  df_reviews = df_valid.dropna(subset=["review_score"])
  ```

- For all other columns, do NOT drop nulls unless the business question requires it.
  Document the reason in a comment when you do.

---

## Pandas Coding Standards

### 1. Column Pruning (RAM efficiency)

Only load the columns needed to answer the specific question. Always pass
`engine="pyarrow"` for maximum memory efficiency and I/O speed:

```python
# Good
cols = ["order_id", "delivery_delay_days", "seller_state", "review_score"]
df = pd.read_parquet("data/raw/obt_cache.parquet", columns=cols, engine="pyarrow")

# Bad — wrong engine, loads all ~50 columns
df = pd.read_parquet("data/raw/obt_cache.parquet")
```

### 2. Vectorised Operations Only

Never use `.apply()` or `iterrows()` when a vectorised alternative exists.

```python
# Good
df["is_late"] = df["delivery_delay_days"] > 0

# Bad
df["is_late"] = df["delivery_delay_days"].apply(lambda x: x > 0)
```

### 3. Method Chaining

Prefer readable method chains over intermediate variables for transforms:

```python
result = (
    df_valid.query("delivery_delay_days > 0")
    .groupby("seller_state", as_index=False)["delivery_delay_days"]
    .agg(mean_delay="mean", order_count="count")
    .sort_values("mean_delay", ascending=False)
)
```

### 4. Aggregation Naming

Always use named aggregations (`agg(col_name="func")`) — never anonymous `.agg("mean")`.

---

## `src/` Function Standards (Type Hints & Docstrings)

Every function written in the `src/` directory **must** include:

1. **Strict Python type hints** on all parameters and return values.
2. **Google-style docstrings** with `Args:`, `Returns:`, and `Raises:` sections.

```python
import pandas as pd


def calculate_freight_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """Compute freight cost as a percentage of item price per order line.

    Args:
        df: Validated OBT DataFrame containing ``price`` and
            ``freight_value`` columns. Must already be filtered by
            ``is_valid_logistics == 1`` and ``is_valid_product == 1``.

    Returns:
        The input DataFrame with a new ``freight_ratio`` column added
        (float, range 0–1+).

    Raises:
        ValueError: If ``price`` or ``freight_value`` columns are absent.
    """
    if not {"price", "freight_value"}.issubset(df.columns):
        raise ValueError("DataFrame must contain 'price' and 'freight_value'.")
    df = df.copy()
    df["freight_ratio"] = df["freight_value"] / df["price"]
    return df
```

---

## Seaborn / Matplotlib Visualisation Standards

All charts must be **executive-ready**. Every chart requires:

1. `sns.set_theme(style="whitegrid")` called at the top of the cell or helper function.
2. A descriptive `ax.set_title()` — business-level, not technical (e.g. _"Top 10 States
   by Average Delivery Delay (Days)"_ not _"delivery_delay_days by seller_state"_).
3. Clean axis labels via `ax.set_xlabel()` / `ax.set_ylabel()`.
4. Save to `visuals/` using `fig.savefig("visuals/<name>.png", dpi=150,
bbox_inches="tight")`.
5. Always create a figure explicitly: `fig, ax = plt.subplots(figsize=(12, 5))`.

```python
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid")

fig, ax = plt.subplots(figsize=(12, 5))
sns.barplot(data=result, x="seller_state", y="mean_delay", palette="flare", ax=ax)
ax.set_title("Top 10 States by Average Delivery Delay (Days)", fontsize=14, pad=12)
ax.set_xlabel("Seller State")
ax.set_ylabel("Mean Delay (Days)")
fig.savefig("visuals/delay_by_state.png", dpi=150, bbox_inches="tight")
plt.show()
```

---

## Pandera Schema Validation (Data Contract)

Treat the OBT as an **external data contract**. Validate it immediately after loading
to catch upstream dbt pipeline regressions before any KPI is calculated. If the data
violates the contract, the script must **intentionally raise and halt** — never silently
continue with corrupt data. Define schemas in `src/diagnostic_utils.py`, not inline.

```python
import pandera as pa

obt_schema = pa.DataFrameSchema(
    {
        "order_id": pa.Column(str, nullable=False),
        "order_item_id": pa.Column(int, nullable=False),
        "price": pa.Column(float, checks=pa.Check.greater_than(0)),
        "freight_value": pa.Column(float, checks=pa.Check.greater_than_or_equal_to(0)),
        "order_purchase_timestamp": pa.Column("datetime64[ns]", nullable=False),
        "order_estimated_delivery_date": pa.Column("datetime64[ns]", nullable=True),
        "order_delivered_customer_date": pa.Column("datetime64[ns]", nullable=True),
        "review_score": pa.Column(
            float, nullable=True, checks=pa.Check.in_range(1, 5)
        ),
        "is_valid_logistics": pa.Column(int, checks=pa.Check.isin([0, 1])),
        "is_valid_product": pa.Column(int, checks=pa.Check.isin([0, 1])),
    },
    # Fail loudly — do not coerce or skip invalid rows.
    coerce=False,
)
```

---

## Code Formatting Rules (Ruff — 88-char line limit)

- Max line length: **88 characters**.
- All imports must be at the top of the file/cell, grouped: stdlib → third-party →
  local (`src`).
- No unused imports — ruff will flag and auto-remove them on commit.
- String quotes: **double quotes** (`"`).

```python
# Import order
import warnings

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src.diagnostic_utils import plot_delay_distribution
```

---

## Notebook Cell Structure Convention

Every notebook analysis cell should follow this pattern:

```python
# ── [Section Title] ──────────────────────────────────────────────────────────
# Business context: 1-2 sentences explaining WHY this analysis matters.

cols = [...]
df = pd.read_parquet("data/raw/obt_cache.parquet", columns=cols, engine="pyarrow")
df_valid = df.query("is_valid_logistics == 1 and is_valid_product == 1")

# Transform
result = (...)

# Visualise
fig, ax = plt.subplots(figsize=(12, 5))
# ... chart code
plt.show()
```

---

## Dev Workflow (ADLC — Analytics Development Life Cycle)

Work follows **GitFlow**: GitHub Issue → feature branch → Pull Request →
GitHub Actions CI (ruff lint gate) → merge → Tag/Release.

```bash
# Install / sync all dependencies (uv.lock guarantees Dev/Prod reproducibility)
uv sync

# Run a script or notebook kernel with the managed venv
uv run python src/diagnostic_utils.py

# Lint and format (Ruff only — do NOT suggest black, flake8, or isort)
uv run ruff check . --fix
uv run ruff format .

# Pre-commit: runs ruff + nbstripout (strips notebook outputs for clean PRs)
pre-commit run --all-files
```

---

## What Copilot Should NEVER Do

| Rule                                                          | Reason                                             |
| ------------------------------------------------------------- | -------------------------------------------------- |
| Do NOT query Snowflake in notebook cells                      | FinOps — cost control                              |
| Do NOT use `.apply()`, `iterrows()`, or `for` loops           | Performance — always use vectorised ops            |
| Do NOT fill `review_score` NaNs with 0                        | Corrupts statistical averages                      |
| Do NOT ignore `is_valid_logistics` / `is_valid_product` flags | Data quality gates — every metric depends on these |
| Do NOT put reusable functions inline in notebooks             | Architecture — belongs in `src/`                   |
| Do NOT load all columns from the parquet                      | RAM efficiency — always prune columns              |
| Do NOT omit `engine="pyarrow"` from `pd.read_parquet()`       | Performance — PyArrow is significantly faster      |
| Do NOT write `src/` functions without type hints + docstrings | Maintainability — enterprise code standard         |
| Do NOT write code to clean raw CSVs                           | dbt handles all cleaning upstream                  |
| Do NOT suggest `black`, `flake8`, or `isort`                  | Ruff replaces all three — pyproject.toml governs   |
