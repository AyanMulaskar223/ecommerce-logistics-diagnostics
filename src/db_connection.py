import logging
import os
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

# Configure enterprise-grade logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def extract_obt_to_parquet() -> None:
    """
    Connects to Snowflake via secure environment variables, extracts the
    obt_logistics_diagnostics table, and serializes it to a local Parquet cache.

    Raises:
        snowflake.connector.errors.DatabaseError: If connection or query fails.
    """
    # 1. Load secure credentials from .env
    load_dotenv()

    # 2. Define the exact file path for the FinOps cache
    output_dir = Path("data/raw")
    output_file = output_dir / "obt_cache.parquet"

    # Ensure the directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # 3. Validate all required credentials are present before attempting connection.
    # Fails loudly and immediately rather than after a 5-second network timeout.
    required_vars = [
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        raise OSError(
            f"Missing required environment variables: {missing}. Check your .env file."
        )

    database = os.getenv("SNOWFLAKE_DATABASE")
    schema = os.getenv("SNOWFLAKE_SCHEMA")
    query = f"SELECT * FROM {database}.{schema}.obt_logistics_diagnostics;"

    conn = None
    try:
        logging.info("Initiating secure connection to Snowflake...")
        conn = snowflake.connector.connect(
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            database=database,
            schema=schema,
        )

        cursor = conn.cursor()

        # Introspect available warehouses so we can diagnose name/permission issues.
        cursor.execute("SHOW WAREHOUSES;")
        available = [row[0] for row in cursor.fetchall()]
        logging.info(f"Warehouses visible to this role: {available}")

        warehouse = os.getenv("SNOWFLAKE_WAREHOUSE")
        if warehouse not in available:
            raise OSError(
                f"Warehouse '{warehouse}' not found or not accessible. "
                f"Available warehouses: {available}. "
                "Update SNOWFLAKE_WAREHOUSE in your .env to one of the above."
            )

        cursor.execute(f"USE WAREHOUSE {warehouse};")
        logging.info(f"Warehouse activated: {warehouse}")

        # 4. Execute query and fetch directly into a highly-optimized Pandas DataFrame
        logging.info("Executing OBT extraction query...")
        cursor.execute(query)

        # fetch_pandas_all() is the fastest Snowflake method (uses PyArrow under the hood)
        df: pd.DataFrame = cursor.fetch_pandas_all()
        logging.info(f"Successfully extracted {len(df)} rows.")

        # 5. Serialize to Parquet (The FinOps Flex)
        logging.info("Serializing DataFrame to local Parquet cache...")
        df.to_parquet(output_file, engine="pyarrow", index=False)
        logging.info(f"✅ Cache successfully saved to: {output_file}")

    except Exception as e:
        logging.error(f"Extraction failed: {e}")
        raise

    finally:
        # 6. Always close the connection to stop cloud compute billing
        if conn:
            conn.close()
            logging.info("Snowflake connection securely closed.")


if __name__ == "__main__":
    extract_obt_to_parquet()
