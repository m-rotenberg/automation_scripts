from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

from snowflake_connection_public import coerce_df_to_schema, get_snowflake_connection

TARGET_DATABASE = "FINANCE"
TARGET_SCHEMA = "PRODUCTION"
TARGET_TABLE = "CLOUD_COST"
STAGE_TABLE = "CLOUD_COST_STAGE"

DEV_SUBSCRIPTIONS: dict[str, str | None] = {
    "dev": os.getenv("DEV_SUBSCRIPTION_ID"),
    "prod": os.getenv("PROD_SUBSCRIPTION_ID"),
}


def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "resource": "https://management.azure.com/",
    }
    resp = requests.post(url, data=data)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _request_with_retry(method: str, url: str, max_retries: int = 5, **kwargs) -> requests.Response:
    for attempt in range(max_retries):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            time.sleep(wait)
        elif resp.status_code == 504:
            time.sleep(30 * (attempt + 1))
        else:
            return resp
    resp.raise_for_status()
    return resp


def fetch_costs_azure(token: str, subscription_id: str, start_date: str, end_date: str) -> list[dict]:
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Consumption/usageDetails"
        f"?api-version=2023-05-01&startDate={start_date}&endDate={end_date}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    rows: list[dict] = []
    while url:
        resp = _request_with_retry("GET", url, headers=headers)
        resp.raise_for_status()
        js = resp.json()
        for item in js.get("value", []):
            props = item.get("properties", {})
            additional = props.pop("additionalProperties", {}) or {}
            rows.append({**props, **additional})
        url = js.get("nextLink")
    return rows


def normalize_costs_azure(rows: list[dict], source_name: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.insert(0, "source", source_name)
    return df


SCHEMA = [
    ("date", "DATE"),
    ("source", "STRING"),
    ("resource_name", "STRING"),
    ("quantity", "FLOAT"),
    ("cost_usd", "FLOAT"),
    ("billing_currency", "STRING"),
]


def main() -> None:
    load_dotenv()
    today = date.today()
    start_date = today.replace(day=1).strftime("%Y-%m-%d")
    end_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    token = get_access_token(tenant_id, client_id, client_secret)

    frames: list[pd.DataFrame] = []
    for name, sub_id in DEV_SUBSCRIPTIONS.items():
        if not sub_id:
            continue
        raw = fetch_costs_azure(token, sub_id, start_date, end_date)
        df = normalize_costs_azure(raw, name)
        if not df.empty:
            frames.append(df)

    if not frames:
        return

    combined = pd.concat(frames, ignore_index=True)
    conn = get_snowflake_connection()
    try:
        df_out = coerce_df_to_schema(combined, SCHEMA)
        conn.cursor().execute(f'DROP TABLE IF EXISTS {TARGET_DATABASE}.{TARGET_SCHEMA}.{STAGE_TABLE}')
        write_pandas(
            conn=conn,
            df=df_out,
            table_name=STAGE_TABLE,
            database=TARGET_DATABASE,
            schema=TARGET_SCHEMA,
            auto_create_table=True,
            overwrite=True,
            use_logical_type=True,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
