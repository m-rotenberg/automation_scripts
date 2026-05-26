#!/usr/bin/env python3
"""Deploy semantic model YAML definitions to Snowflake.

Reads YAML files from semantic_layer/views/ and deploys them using
SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML.

Usage:
    python deploy_semantic_views.py --database ANALYTICS_DEV
    python deploy_semantic_views.py --database ANALYTICS_DEV --verify-only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from glob import glob
from pathlib import Path

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

# Load .env file if it exists (for local development)
load_dotenv()

SEMANTIC_SCHEMA = "SEMANTIC"
STAGING_SCHEMA = "STAGING"
VIEWS_DIR = Path(__file__).resolve().parent.parent / "semantic_layer" / "semantic_views"
STAGING_SQL_DIR = Path(__file__).resolve().parent.parent / "semantic_layer" / "sql" / "staging"


def _load_private_key_der() -> bytes:
    """Load private key from file path or base64-encoded string."""
    # Prefer reading from file path (local dev)
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        pem_str = Path(key_path).expanduser().read_text()
    else:
        # Fall back to base64-encoded key (CI/CD environments)
        b64 = os.environ["SNOWFLAKE_PRIVATE_KEY_BASE64"]
        pem = base64.b64decode(b64.strip())
        pem_str = pem.decode("utf-8")
        # Fix single-line PEM encoding that some secret managers produce
        pem_str = pem_str.replace(
            "-----BEGIN PRIVATE KEY----- ", "-----BEGIN PRIVATE KEY-----\n"
        )
        pem_str = pem_str.replace(
            " -----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----"
        )

    key = serialization.load_pem_private_key(pem_str.encode("utf-8"), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_connection(database: str) -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        private_key=_load_private_key_der(),
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=database,
        role=os.environ["SNOWFLAKE_ROLE"],
    )


def ensure_schema(conn: snowflake.connector.SnowflakeConnection, database: str):
    """Ensure SEMANTIC and STAGING schemas exist."""
    conn.cursor().execute(
        f'CREATE SCHEMA IF NOT EXISTS "{database}"."{SEMANTIC_SCHEMA}"'
    )
    conn.cursor().execute(
        f'CREATE SCHEMA IF NOT EXISTS "{database}"."{STAGING_SCHEMA}" '
        f'COMMENT = \'Staging views for staging artifacts - can be migrated to dbt later\''
    )


def grant_access(conn: snowflake.connector.SnowflakeConnection, database: str):
    """Grant USAGE on schemas and SELECT on all views to consumer roles.

    Grants access to both SEMANTIC and STAGING schemas:
    - SEMANTIC: semantic models
    - STAGING: staging artifacts

    Reads a comma-separated list of role names from the SNOWFLAKE_GRANT_TO_ROLES
    env var. If the var is unset or empty the function is a no-op.
    """
    raw = os.environ.get("SNOWFLAKE_GRANT_TO_ROLES", "")
    roles = [r.strip() for r in raw.split(",") if r.strip()]
    if not roles:
        return

    semantic_schema_fqn = f'"{database}"."{SEMANTIC_SCHEMA}"'
    staging_schema_fqn = f'"{database}"."{STAGING_SCHEMA}"'

    for role in roles:
        print(f"  Granting access to role {role} ...")

        # Grant on SEMANTIC schema (semantic models)
        conn.cursor().execute(
            f'GRANT USAGE ON SCHEMA {semantic_schema_fqn} TO ROLE "{role}"'
        )
        conn.cursor().execute(
            f'GRANT SELECT ON ALL SEMANTIC VIEWS IN SCHEMA {semantic_schema_fqn} TO ROLE "{role}"'
        )

        # Grant on STAGING schema (regular views)
        conn.cursor().execute(
            f'GRANT USAGE ON SCHEMA {staging_schema_fqn} TO ROLE "{role}"'
        )
        conn.cursor().execute(
            f'GRANT SELECT ON ALL VIEWS IN SCHEMA {staging_schema_fqn} TO ROLE "{role}"'
        )

    print(f"  Grants applied to {len(roles)} role(s) on SEMANTIC and STAGING schemas")


def deploy_staging_views(
    conn: snowflake.connector.SnowflakeConnection, database: str
) -> list[dict]:
    """Deploy staging SQL views to the STAGING schema."""
    sql_files = sorted([Path(p) for p in glob(str(STAGING_SQL_DIR / "*.sql"))])

    if not sql_files:
        print("No staging SQL files found - skipping staging view deployment")
        return []

    print(f"\nDeploying {len(sql_files)} staging view(s) to {database}.{STAGING_SCHEMA}...")
    results = []

    for sql_path in sql_files:
        filename = sql_path.name
        sql_content = sql_path.read_text()

        try:
            # Execute the CREATE OR REPLACE VIEW statement
            conn.cursor().execute(sql_content)
            print(f"  [{filename}] deployed")
            results.append({"file": filename, "status": "deployed", "error": None})
        except Exception as e:
            print(f"  [{filename}] FAILED: {e}", file=sys.stderr)
            results.append({"file": filename, "status": "failed", "error": str(e)})

    return results


def deploy_yaml(
    conn: snowflake.connector.SnowflakeConnection,
    database: str,
    yaml_path: Path,
    verify_only: bool,
) -> dict:
    filename = yaml_path.name
    yaml_content = yaml_path.read_text()
    target = f"{database}.{SEMANTIC_SCHEMA}"

    sql = (
        f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML("
        f"'{target}', $${yaml_content}$$, TRUE)"
        if verify_only
        else f"CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML("
        f"'{target}', $${yaml_content}$$)"
    )

    try:
        result = conn.cursor().execute(sql).fetchone()
        status = "verified" if verify_only else "deployed"
        msg = result[0] if result else "OK"
        print(f"  [{filename}] {status}: {msg}")
        return {"file": filename, "status": status, "message": msg, "error": None}
    except Exception as e:
        print(f"  [{filename}] FAILED: {e}", file=sys.stderr)
        return {"file": filename, "status": "failed", "message": None, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Deploy semantic models to Snowflake")
    parser.add_argument("--database", required=True, help="Target Snowflake database")
    parser.add_argument(
        "--verify-only", action="store_true", help="Validate YAML without deploying"
    )
    args = parser.parse_args()

    yaml_files = sorted(
        [Path(p) for p in glob(str(VIEWS_DIR / "*.yaml"))]
        + [Path(p) for p in glob(str(VIEWS_DIR / "*.yml"))]
    )

    if not yaml_files:
        print("No YAML files found in semantic_views/")
        sys.exit(1)

    mode = "verify-only" if args.verify_only else "deploy"
    print(f"Found {len(yaml_files)} semantic model definition(s)")
    print(f"Target: {args.database}.{SEMANTIC_SCHEMA}")
    print(f"Mode:   {mode}")
    print()

    conn = get_connection(args.database)

    # Ensure schemas exist
    ensure_schema(conn, args.database)

    # Deploy staging artifacts first (unless verify-only mode)
    staging_results = []
    if not args.verify_only:
        staging_results = deploy_staging_views(conn, args.database)
        staging_failed = [r for r in staging_results if r["status"] == "failed"]
        if staging_failed:
            print(f"\nERROR: {len(staging_failed)} staging view(s) failed - cannot proceed")
            for r in staging_failed:
                print(f"  - {r['file']}: {r['error']}")
            conn.close()
            sys.exit(1)

    # Deploy semantic models
    print(f"\n{'Validating' if args.verify_only else 'Deploying'} {len(yaml_files)} semantic model(s)...")
    results = []
    for yaml_path in yaml_files:
        result = deploy_yaml(conn, args.database, yaml_path, args.verify_only)
        results.append(result)

    # -- Grants (deploy mode only, after all views succeed) --
    failed = [r for r in results if r["status"] == "failed"]
    if not args.verify_only and not failed:
        grant_access(conn, args.database)

    conn.close()

    # -- Summary --
    print()
    if failed:
        print(f"FAILED: {len(failed)} of {len(results)} file(s)")
        for r in failed:
            print(f"  - {r['file']}: {r['error']}")
        # Output structured report for CI
        print(f"\n::error::{json.dumps(failed)}")
        sys.exit(1)
    else:
        action = "validated" if args.verify_only else "deployed"
        print(f"SUCCESS: {len(results)} file(s) {action}")


if __name__ == "__main__":
    main()
