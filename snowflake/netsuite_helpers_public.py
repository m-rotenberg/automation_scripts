from __future__ import annotations

import hashlib
import os
import time

import pandas as pd
import requests
from snowflake.connector.pandas_tools import write_pandas

from snowflake_connection_public import coerce_df_to_schema, push_df_to_snowflake

RAW_SCHEMA = "RAW"
BACKUP_SCHEMA = "BACKUP"


def fetch_all_dataset_records(
    auth,
    dataset_id: str,
    limit: int = 1000,
    page_sleep: float = 1.0,
    max_retries: int = 5,
    retry_wait: int = 60,
):
    company_id = os.getenv("COMPANY_ID")
    base_url = f"https://{company_id}.suitetalk.api.example.com"
    endpoint = f"/services/rest/query/v1/dataset/{dataset_id}/result"
    offset, all_items = 0, []

    while True:
        url = f"{base_url}{endpoint}?limit={limit}&offset={offset}"
        response = requests.get(url, auth=auth, headers={"Prefer": "transient"})
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", retry_wait))
            time.sleep(wait)
            continue
        if response.status_code != 200:
            break
        data = response.json()
        all_items.extend(data.get("items", []))
        if not data.get("hasMore"):
            break
        offset += limit
        time.sleep(page_sleep)

    return all_items


def to_id_map(items, id_key="id", value_key=None):
    return {
        str(r[id_key]): r.get(value_key)
        for r in items
        if r.get(id_key) is not None and r.get(value_key) is not None
    }


def fetch_dataset(auth, config):
    items = fetch_all_dataset_records(auth, dataset_id=config["dataset_id"])
    df = pd.DataFrame(items)

    if config.get("strip_custrecord_prefix"):
        df.rename(columns=lambda x: x.replace("custrecord_", ""), inplace=True)

    if config.get("rename_cols"):
        df.rename(columns=config["rename_cols"], inplace=True)

    for col, lookup_map in config.get("lookup_cols", {}).items():
        if col in df.columns:
            df[col] = df[col].astype("string").map(lookup_map).fillna(df[col])

    df.drop(columns=config.get("drop_cols", []), inplace=True, errors="ignore")
    return df


def overwrite_df_to_snowflake(conn, df, table_name, schema=None):
    if df is None or df.empty:
        return
    df_out = coerce_df_to_schema(df, schema) if schema is not None else df.copy()
    conn.cursor().execute(f'DROP TABLE IF EXISTS {RAW_SCHEMA}."{table_name}"')
    write_pandas(
        conn=conn,
        df=df_out,
        table_name=table_name,
        schema=RAW_SCHEMA,
        auto_create_table=True,
        overwrite=False,
        use_logical_type=True,
    )


def upsert_df_to_snowflake(conn, df, table_name, id_col, schema=None):
    if id_col is None or df is None or df.empty:
        return
    df_out = coerce_df_to_schema(df, schema) if schema is not None else df.copy()
    id_col_upper = id_col.upper()
    df_out.columns = [c.upper() for c in df_out.columns]
    df_out["ROW_HASH"] = df_out.drop(columns=[id_col_upper]).apply(
        lambda row: hashlib.md5("|".join(str(v) for v in row).encode()).hexdigest(),
        axis=1,
    )
    staging = f"{table_name}_STAGING"
    write_pandas(conn=conn, df=df_out, table_name=staging, schema=RAW_SCHEMA, auto_create_table=True, overwrite=True, use_logical_type=True)
    push_df_to_snowflake(conn, df_out, table_name, schema=schema)
    conn.cursor().execute(f'DROP TABLE IF EXISTS {RAW_SCHEMA}."{staging}"')
