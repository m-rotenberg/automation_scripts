from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from salesforce_config_public import REPORT_REGISTRY
from salesforce_reports_public import (
    authenticate_salesforce,
    enrich_dataframe,
    flatten_report,
    get_report,
    prepare_for_snowflake,
    rename_id_columns,
)
from snowflake_connection_public import get_snowflake_connection, push_df_to_snowflake


def process_report(
    sf: Any,
    conn: Any,
    config: Dict[str, Any],
    caches: Dict[str, Dict[str, str]],
) -> None:
    """
    Fetch, transform, and load one Salesforce report into Snowflake.

    Each report is written twice:
      1. Full load  → FINANCE.SALESFORCE.<table_name>  (truncate + replace)
      2. Snapshot   → FINANCE.BACKUP.<table_name>       (append with SNAPSHOT_AT)
    """
    print(f"\n[{config['table_name']}] Fetching report {config['report_id']}...")
    payload = get_report(sf, config["report_id"])
    df = flatten_report(payload)
    print(f"  Fetched {len(df)} rows, {len(df.columns)} columns")

    df = rename_id_columns(df, config["rename_cols"])
    df = enrich_dataframe(df, sf=sf, object_mapping=config["object_mapping"], caches=caches)

    schema = config.get("schema")
    if schema is not None:
        # Schema path: stamp loaded_at so it can be declared in the schema,
        # then coerce_df_to_schema enforces exact column selection and types.
        df["loaded_at"] = datetime.now(timezone.utc)
    else:
        # No-schema path: prepare_for_snowflake handles type inference + loaded_at.
        df = prepare_for_snowflake(df)

    push_df_to_snowflake(conn, df, config["table_name"], schema=schema)
    push_df_to_snowflake(conn, df, config["table_name"], schema=schema, snapshot=True)


def main() -> None:
    sf = authenticate_salesforce()
    conn = get_snowflake_connection()
    caches: Dict[str, Dict[str, str]] = {}

    try:
        for config in REPORT_REGISTRY:
            process_report(sf, conn, config, caches)
        print("\nAll reports loaded.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
