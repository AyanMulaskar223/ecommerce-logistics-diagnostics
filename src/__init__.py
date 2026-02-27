"""
ecommerce-logistics-diagnostics — src package
==============================================
Analytical helpers and data contracts for the Olist Logistics Root-Cause
Diagnostics pipeline (Phase 2).

Modules
-------
data_contracts
    Pandera DataFrameSchema enforcing the dbt Gold-layer OBT data contract.
db_connection
    Snowflake connector — cache-refresh only; never called from notebooks.
diagnostic_utils
    All plotting, transformation, and KPI helper functions used by the
    analysis notebooks.
"""
