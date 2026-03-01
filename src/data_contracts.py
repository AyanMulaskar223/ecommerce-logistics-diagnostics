import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

# ---------------------------------------------------------
# RUNTIME DATA CONTRACT: OBT Logistics Diagnostics
# ---------------------------------------------------------
obt_schema = DataFrameSchema(
    {
        # 1. IDENTIFIERS (The Grain)
        "obt_sk": Column(str, nullable=False, unique=True),
        "order_id": Column(str, nullable=False),
        "order_item_id": Column(int, Check.ge(1), nullable=False),
        "product_id": Column(str, nullable=False),
        "customer_unique_id": Column(str, nullable=False),
        # 2. TIMESTAMPS
        # pa.Timestamp accepts any precision (ns, us, ms) — do NOT hard-code
        # "datetime64[ns]" because Snowflake via PyArrow produces datetime64[us].
        # Hard-coding the precision causes a SchemaError on every single load.
        "order_purchase_timestamp": Column(pa.Timestamp, nullable=False),
        "order_estimated_delivery_date": Column(pa.Timestamp, nullable=False),
        # Nullable because ghost deliveries/lost packages may never get a delivery date
        "order_delivered_customer_date": Column(pa.Timestamp, nullable=True),
        # 3. FINANCIALS & GEOGRAPHY
        "price": Column(float, Check.ge(0.0), nullable=False),
        "freight_value": Column(float, Check.ge(0.0), nullable=False),
        # Regex validation: Must be exactly two uppercase letters (e.g., 'SP', 'AM')
        "customer_state": Column(str, Check.str_matches(r"^[A-Z]{2}$"), nullable=False),
        "seller_state": Column(str, Check.str_matches(r"^[A-Z]{2}$"), nullable=False),
        # 4. PRODUCT SPECS & FEEDBACK
        # product_weight_g: allow 0.0 (unknown weight) and >0 (actual weight).
        # Filtering for >0 happens at analysis time when needed (Q2 correlation).
        "product_weight_g": Column(float, Check.ge(0.0), nullable=True),
        # Review scores must be exact integers between 1 and 5, but can be NaN
        "review_score": Column(
            float, Check.isin([1.0, 2.0, 3.0, 4.0, 5.0]), nullable=True
        ),
        # 5. DATA QUALITY FLAGS (The Critical Gates)
        "is_valid_logistics": Column(int, Check.isin([0, 1]), nullable=False),
        "logistics_issue_reason": Column(str, nullable=True),
        "is_valid_product": Column(int, Check.isin([0, 1]), nullable=False),
        "product_issue_reason": Column(str, nullable=True),
    },
    # The Senior Flex: strict=True means if dbt accidentally adds an undocumented
    # column to the table, the notebook will intentionally fail.
    strict=True,
    coerce=True,  # Automatically force PyArrow types into this exact shape
)
