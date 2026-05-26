from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from simple_salesforce import Salesforce


def load_salesforce_env(env_path: Optional[str] = None) -> str:
    """Load Salesforce credentials from a .env file and return its resolved path."""
    if env_path is None:
        env_path = str(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv(dotenv_path=env_path)
    return env_path


def _load_private_key_pem() -> str:
    """Read SF_PRIVATE_KEY_BASE64 from the environment and return a properly formatted PEM string."""
    private_key_b64 = os.getenv("SF_PRIVATE_KEY_BASE64")
    if not private_key_b64:
        raise ValueError("SF_PRIVATE_KEY_BASE64 is not set")

    pem_str = base64.b64decode(private_key_b64.strip()).decode("utf-8").strip()

    match = re.match(r"(-----BEGIN [^-]+-----)(.*?)(-----END [^-]+-----)", pem_str, re.DOTALL)
    if not match:
        raise ValueError("Could not parse PEM structure — check your base64 encoding")

    raw_body = re.sub(r"\s+", "", match.group(2))
    body = "\n".join(raw_body[i : i + 64] for i in range(0, len(raw_body), 64))

    return f"{match.group(1).strip()}\n{body}\n{match.group(3).strip()}\n"


def authenticate_salesforce(env_path: Optional[str] = None) -> Salesforce:
    """Authenticate and return a Salesforce connection using JWT (private key) authentication."""
    load_salesforce_env(env_path=env_path)

    username = os.getenv("SF_USERNAME")
    consumer_key = os.getenv("SF_CONSUMER_KEY")
    domain = os.getenv("SF_DOMAIN", "login")

    missing = [
        key
        for key, value in {
            "SF_USERNAME": username,
            "SF_CONSUMER_KEY": consumer_key,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing Salesforce credentials in environment: {missing}")

    return Salesforce(
        username=username,
        consumer_key=consumer_key,
        privatekey=_load_private_key_pem(),
        domain=domain,
    )


def get_report(sf: Salesforce, report_id: str, include_details: bool = True) -> Dict[str, Any]:
    """Fetch a Salesforce Analytics report payload."""
    params = {"includeDetails": str(include_details).lower()}
    return sf.restful(f"analytics/reports/{report_id}", params=params)


def to_snake_case(value: str) -> str:
    """Convert a column name to SQL-friendly snake_case."""
    value = (value or "").strip()
    value = value.replace(".", "_").replace("__", "_")
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"_+", "_", value).strip("_").lower()
    if not value:
        value = "column"
    if value[0].isdigit():
        value = f"col_{value}"
    return value


def _dedupe_columns(columns: Iterable[str]) -> List[str]:
    """Normalize and deduplicate columns while preserving order."""
    counts: Dict[str, int] = {}
    deduped: List[str] = []
    for col in columns:
        base = to_snake_case(col)
        counts[base] = counts.get(base, 0) + 1
        deduped.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return deduped


def _safe_cell_value(cell: Dict[str, Any]) -> Any:
    """Extract the best scalar representation of a Salesforce Analytics data cell."""
    value = cell.get("value")

    if isinstance(value, dict):
        for key in ("value", "amount", "name", "id"):
            nested = value.get(key)
            if nested is not None and not isinstance(nested, (dict, list)):
                return nested
        label = cell.get("label")
        return label if label not in (None, "") else str(value)

    if isinstance(value, list):
        return "; ".join(str(v) for v in value)

    if value is not None:
        return value

    return cell.get("label")


def flatten_report(report_payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Flatten a Salesforce report payload into a row-level DataFrame.

    The function uses report detail columns in metadata and maps each row's `dataCells`
    by positional index, retaining trailing/null columns by pre-seeding each record with
    all expected fields.
    """
    report_metadata = report_payload.get("reportMetadata", {})
    extended_metadata = report_payload.get("reportExtendedMetadata", {})
    detail_columns = report_metadata.get("detailColumns", [])
    detail_info = extended_metadata.get("detailColumnInfo", {})

    detail_labels = [detail_info.get(col, {}).get("label", col) for col in detail_columns]
    output_columns = _dedupe_columns(detail_labels)

    rows: List[Dict[str, Any]] = []
    for bucket in (report_payload.get("factMap") or {}).values():
        for row in (bucket.get("rows") or []):
            record: Dict[str, Any] = {col: None for col in output_columns}
            data_cells = row.get("dataCells") or []
            max_idx = max(len(output_columns), len(data_cells))

            for idx in range(max_idx):
                if idx >= len(output_columns):
                    continue
                if idx >= len(data_cells):
                    continue
                record[output_columns[idx]] = _safe_cell_value(data_cells[idx])
            rows.append(record)

    return pd.DataFrame(rows, columns=output_columns)


def rename_id_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """Rename only existing columns using a source->target mapping."""
    available_mapping = {src: dst for src, dst in mapping.items() if src in df.columns}
    return df.rename(columns=available_mapping)


def _normalize_sf_id(value: Any) -> Optional[str]:
    """Normalize potential Salesforce IDs and ignore placeholders."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    if re.fullmatch(r"[a-zA-Z0-9]{15}|[a-zA-Z0-9]{18}", text):
        return text
    return None


def _collect_unique_ids(df: pd.DataFrame, columns: Sequence[str]) -> List[str]:
    """Collect unique, valid Salesforce IDs from selected DataFrame columns."""
    ids: List[str] = []
    seen = set()
    for col in columns:
        if col not in df.columns:
            continue
        for value in df[col].tolist():
            sf_id = _normalize_sf_id(value)
            if sf_id and sf_id not in seen:
                seen.add(sf_id)
                ids.append(sf_id)
    return ids


def fetch_sobjects_by_ids(
    sf: Salesforce,
    sobject_name: str,
    ids: Sequence[str],
    cache: Optional[Dict[str, str]] = None,
    batch_size: int = 200,
) -> Dict[str, str]:
    """
    Fetch `Id, Name` from a Salesforce object for a set of IDs.

    The function deduplicates queries by checking a cache first and safely returns
    without executing SOQL if no IDs are provided.
    """
    cache = cache or {}
    ids_to_query = [sf_id for sf_id in ids if sf_id not in cache]
    if not ids_to_query:
        return cache

    for i in range(0, len(ids_to_query), batch_size):
        chunk = ids_to_query[i : i + batch_size]
        quoted_ids = ", ".join(f"'{sf_id}'" for sf_id in chunk)
        query = f"SELECT Id, Name FROM {sobject_name} WHERE Id IN ({quoted_ids})"
        result = sf.query_all(query)
        records = result.get("records", [])

        for record in records:
            record_id = record.get("Id")
            if record_id:
                cache[record_id] = record.get("Name") or "-"

        returned_ids = {record.get("Id") for record in records if record.get("Id")}
        for sf_id in chunk:
            if sf_id not in returned_ids:
                cache[sf_id] = "-"

    return cache


def map_ids_to_names(series: pd.Series, id_to_name: Dict[str, str], default_value: str = "-") -> pd.Series:
    """Map a Series of Salesforce IDs into display names with a stable default."""
    normalized_ids = series.apply(_normalize_sf_id)
    return normalized_ids.map(id_to_name).fillna(default_value)


def enrich_dataframe(
    df: pd.DataFrame,
    sf: Salesforce,
    object_mapping: Sequence[Dict[str, Any]],
    caches: Optional[Dict[str, Dict[str, str]]] = None,
) -> pd.DataFrame:
    """
    Generic enrichment engine that maps ID columns to name columns.

    Each mapping item must include:
    - `object`: Salesforce object name (User, Account, Opportunity, ...)
    - `id_columns`: list of columns to gather IDs from
    - `targets`: list of (id_column, name_column) tuples to populate
    """
    caches = caches or {}
    out = df.copy()

    for spec in object_mapping:
        object_name = spec["object"]
        id_columns: List[str] = spec["id_columns"]
        targets: List[Tuple[str, str]] = spec["targets"]

        for id_col in id_columns:
            if id_col not in out.columns:
                out[id_col] = None

        ids = _collect_unique_ids(out, id_columns)
        object_cache = caches.setdefault(object_name, {})
        name_map = fetch_sobjects_by_ids(
            sf=sf,
            sobject_name=object_name,
            ids=ids,
            cache=object_cache,
        )

        for id_col, name_col in targets:
            out[name_col] = map_ids_to_names(out[id_col], name_map, default_value="-")

    return out


def _convert_boolish_series(series: pd.Series) -> pd.Series:
    """Convert common boolean-like strings into pandas nullable boolean dtype."""
    true_values = {"true", "t", "yes", "y", "1"}
    false_values = {"false", "f", "no", "n", "0"}
    normalized = series.astype(str).str.strip().str.lower()
    mask_valid = normalized.isin(true_values.union(false_values)) | series.isna()
    if mask_valid.all():
        mapped = normalized.map({**{x: True for x in true_values}, **{x: False for x in false_values}})
        return mapped.astype("boolean")
    return series


def prepare_for_snowflake(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize DataFrame for Snowflake ingestion.

    - Enforces snake_case column names
    - Applies lightweight type coercion (boolean/date/timestamp/numeric)
    - Explicitly normalizes null values
    - Adds `loaded_at` UTC timestamp
    """
    out = df.copy()
    out.columns = _dedupe_columns(out.columns.tolist())

    for col in out.columns:
        series = out[col]

        if pd.api.types.is_object_dtype(series):
            out[col] = _convert_boolish_series(series)
            series = out[col]

        if any(token in col for token in ["_date", "date_"]):
            parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
            if parsed.notna().any():
                out[col] = parsed.dt.date
                continue

        if any(token in col for token in ["_timestamp", "_datetime", "_at"]):
            parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
            if parsed.notna().any():
                out[col] = parsed
                continue

        if pd.api.types.is_object_dtype(out[col]):
            numeric = pd.to_numeric(out[col], errors="coerce")
            conversion_ratio = numeric.notna().mean() if len(numeric) else 0.0
            if conversion_ratio >= 0.9:
                out[col] = numeric

    out = out.replace({np.nan: None, pd.NaT: None})
    out["loaded_at"] = datetime.now(timezone.utc)
    return out
