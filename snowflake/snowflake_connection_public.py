from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

FULL_LOAD_SCHEMA = "PRODUCTION"
SNAPSHOT_SCHEMA = "BACKUP"


def _load_private_key_der() -> bytes:
    load_dotenv()
    private_key_b64 = os.getenv("SNOWFLAKE_PRIVATE_KEY_BASE64")
    if not private_key_b64:
        raise ValueError("SNOWFLAKE_PRIVATE_KEY_BASE64 is not set")

    pem = base64.b64decode(private_key_b64.strip())
    pem_str = pem.decode("utf-8")
    pem_str = pem_str.replace("-----BEGIN PRIVATE KEY----- ", "-----BEGIN PRIVATE KEY-----\n")
    pem_str = pem_str.replace(" -----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")

    private_key = serialization.load_pem_private_key(pem_str.encode("utf-8"), password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    load_dotenv()
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        private_key=_load_private_key_der(),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=FULL_LOAD_SCHEMA,
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


def _to_date(s):
    if s is None or s == "" or (isinstance(s, float) and np.isnan(s)):
        return None
    try:
        return pd.to_datetime(s, format="mixed").date()
    except Exception:
        return None


def _to_float(s):
    if s is None or s == "" or (isinstance(s, float) and np.isnan(s)):
        return None
    try:
        if isinstance(s, str):
            if s.startswith("(") and s.endswith(")"):
                s = re.sub(r"[^0-9.\-]", "", s.strip("()"))
                val = float(s) if s else None
                return -val if val is not None else None
            return float(s.replace(",", "")) if s.replace(",", "") else None
        return float(s)
    except Exception:
        return None


def _to_int(s):
    v = _to_float(s)
    return int(v) if v is not None else None


def _to_bool(s):
    if s is None or s == "" or (isinstance(s, float) and np.isnan(s)):
        return None
    if isinstance(s, bool):
        return s
    if isinstance(s, str):
        return s.strip().lower() in ("true", "t", "yes", "y", "1")
    return bool(s)


def coerce_df_to_schema(df: pd.DataFrame, schema: List[Tuple[str, str]]) -> pd.DataFrame:
    df = df.copy()
    col_names = [name for name, _ in schema]
    for name in col_names:
        if name not in df.columns:
            df[name] = None
    df = df[col_names]
    for name, typ in schema:
        if typ == "DATE":
            df[name] = df[name].apply(_to_date)
        elif typ == "FLOAT":
            df[name] = df[name].apply(_to_float)
        elif typ == "INTEGER":
            df[name] = df[name].apply(_to_int)
        elif typ == "BOOLEAN":
            df[name] = df[name].apply(_to_bool)
        elif typ == "TIMESTAMP":
            df[name] = pd.to_datetime(df[name], errors="coerce", utc=True, format="mixed")
        else:
            df[name] = df[name].apply(lambda x: str(x) if x is not None else None)
    df.columns = [c.upper() for c in df.columns]
    return df


def push_df_to_snowflake(
    conn: snowflake.connector.SnowflakeConnection,
    df: pd.DataFrame,
    table_name: str,
    schema: Optional[List[Tuple[str, str]]] = None,
    truncate: bool = True,
    snapshot: bool = False,
) -> None:
    if df is None or df.empty:
        return
    df_out = coerce_df_to_schema(df, schema) if schema is not None else df.copy()
    if snapshot:
        df_out["SNAPSHOT_AT"] = datetime.now(timezone.utc)
        write_pandas(conn=conn, df=df_out, table_name=table_name, schema=SNAPSHOT_SCHEMA, auto_create_table=True, overwrite=False, use_logical_type=True)
    else:
        if schema is not None and truncate:
            conn.cursor().execute(f'DROP TABLE IF EXISTS {FULL_LOAD_SCHEMA}."{table_name}"')
        write_pandas(conn=conn, df=df_out, table_name=table_name, schema=FULL_LOAD_SCHEMA, auto_create_table=True, overwrite=truncate, use_logical_type=True)
