# Olist E-Commerce Logistics Diagnostics

> **Project 2 — Python EDA** | Upstream: [dbt Medallion Architecture (Project 1)](https://github.com)

A Senior-level Exploratory Data Analysis diagnosing a **R$1.2M logistics bottleneck**
in the Olist e-commerce platform. The notebook statistically answers four core business
questions to identify root causes, quantify the 1-star review blast radius, and measure
the impact on repeat purchase rates.

---

## Business Context

| Dimension | Detail |
|-----------|--------|
| **Problem** | 66.7% delivery delay rate in regions like Amazonas (AM) |
| **Financial Risk** | ~R$1.2M revenue at risk from customer churn |
| **Data Source** | One Big Table (OBT) from a dbt-modelled Snowflake pipeline |

---

## Project Structure

```
├── data/
│   ├── raw/                  # obt_cache.parquet — READ ONLY (Snowflake cache)
│   └── processed/            # Aggregated outputs from the notebook
├── notebooks/
│   └── 01_logistics_root_cause_diagnostics.ipynb
├── src/
│   ├── db_connection.py      # Snowflake cache refresh (never called from notebook)
│   └── diagnostic_utils.py  # Reusable plotting & transform helpers
├── visuals/                  # Exported chart PNGs / SVGs
├── pyproject.toml            # Dependencies managed by uv
└── .pre-commit-config.yaml   # nbstripout + ruff hooks
```

---

## The 4 Core Business Questions

| # | Question | Output |
|---|----------|--------|
| Q1 — Baseline | Statistical distribution of delivery delays | Distribution plot + stats by region |
| Q2 — Root Cause | Distance vs. package weight (`product_weight_g`) as delay driver | Correlation matrix + regression plots |
| Q3 — Blast Radius | Delay threshold that triggers 1-star "Silent Detractor" reviews | Threshold chart |
| Q4 — Action Plan | Impact of delays on the 3.0% repeat purchase rate | Cohort comparison |

---

## Setup

```bash
# Install all dependencies (uv.lock guarantees exact reproducibility)
uv sync

# Install git hooks (nbstripout + ruff run automatically on every commit)
uv run pre-commit install

# Launch the notebook
uv run jupyter lab notebooks/01_logistics_root_cause_diagnostics.ipynb
```

---

## Tech Stack

| Layer | Tool | Version |
|-------|------|---------|
| Language | Python | ≥ 3.14 |
| Package Manager | uv | latest |
| Linter / Formatter | ruff | ≥ 0.15 |
| Data Wrangling | pandas | ≥ 3.0 |
| Visualisation | seaborn + matplotlib | ≥ 0.13 / ≥ 3.10 |
| Schema Validation | pandera | ≥ 0.29 |
| Warehouse Client | snowflake-connector-python | ≥ 4.3 |
| Pre-commit Hooks | nbstripout, ruff | — |

---

## Data Architecture

This repository is registered as the official **dbt Exposure** downstream of the
Snowflake Medallion Architecture built in Project 1. Data flows strictly one-way:

```
Snowflake → data/raw/obt_cache.parquet → Notebook → data/processed/
```

> **FinOps Rule:** Never query Snowflake directly from notebook cells.
> Always read from the local Parquet cache.
