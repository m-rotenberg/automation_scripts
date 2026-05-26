# Snowflake Automation Scripts

A collection of Python scripts for extracting data from NetSuite, Salesforce, and Azure and loading it into Snowflake, plus a tool for deploying semantic models.

## Overview

| Script | Purpose |
|---|---|
| `netsuite_to_snowflake_public.py` | Sync NetSuite data → Snowflake |
| `salesforce_to_snowflake_public.py` | Sync Salesforce data → Snowflake |
| `azure_cost_to_snowflake_public.py` | Sync Azure cost data → Snowflake |
| `deploy_semantic_views_public.py` | Deploy semantic model YAML to Snowflake |
| `snowflake_connection_public.py` | Shared Snowflake connection + data utilities |
| `netsuite_helpers_public.py` | NetSuite API helpers (pagination, upsert logic) |
| `netsuite_config_public.py` | NetSuite dataset registry (column mappings, schemas) |
| `salesforce_reports_public.py` | Salesforce API helpers (auth, report flattening, ID enrichment) |
| `salesforce_config_public.py` | Salesforce report registry (column mappings, schemas) |
| `semantic_model_public.yml` | Semantic model definition (Salesforce, NetSuite, Azure) |

**GitHub Actions workflows** (place in `.github/workflows/`):

| Workflow | Schedule | Trigger |
|---|---|---|
| `netsuite_to_snowflake_public.yaml` | Daily 09:00 UTC | `workflow_dispatch` |
| `salesforce_to_snowflake_public.yaml` | Daily 08:00 UTC | `workflow_dispatch` |
| `azure_cost_to_snowflake_public.yaml` | Daily 08:00 UTC | `workflow_dispatch` |

---

## Requirements

Dependencies are managed with [Poetry](https://python-poetry.org/). Install Poetry if you don't have it:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Then install project dependencies:

```bash
cd snowflake
poetry install
```

To run any script:

```bash
poetry run python netsuite_to_snowflake_public.py
```

---

## Authentication

All credentials are loaded from environment variables. Copy the block below into a `.env` file at the project root (never commit this file).

### Snowflake

```env
SNOWFLAKE_USER=
SNOWFLAKE_ACCOUNT=              # e.g. abc123.us-east-1
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=
SNOWFLAKE_ROLE=
SNOWFLAKE_PRIVATE_KEY_BASE64=   # base64-encoded PEM private key (for scripts + CI/CD)
SNOWFLAKE_PRIVATE_KEY_PATH=     # alternatively, path to PEM file (local dev only)
SNOWFLAKE_GRANT_TO_ROLES=       # comma-separated roles to grant access (deploy script only)
```

Snowflake uses key-pair authentication. To generate a key pair:

```bash
openssl genrsa -out rsa_key.pem 2048
openssl rsa -in rsa_key.pem -pubout -out rsa_key.pub.pem
# Encode for use in env var:
base64 -i rsa_key.pem | tr -d '\n'
```

Register the public key on your Snowflake user before connecting.

### NetSuite (OAuth 1.0)

```env
NS_REALM_ID=
NS_COMPANY_ID=
NS_CLIENT_KEY=
NS_CLIENT_SECRET=
NS_TOKEN_ID=
NS_TOKEN_SECRET=
```

### Azure

```env
TENANT_ID=
CLIENT_ID=
CLIENT_SECRET=
DEV_SUBSCRIPTION_ID=
PROD_SUBSCRIPTION_ID=
```

---

## Scripts

### NetSuite → Snowflake

Fetches datasets defined in `netsuite_config_public.py` and loads them into Snowflake. Supports both full overwrite and upsert (via MD5 row hash). Also writes a timestamped snapshot to the `BACKUP` schema.

```bash
python netsuite_to_snowflake_public.py
```

To add or modify which NetSuite datasets are synced, edit `netsuite_config_public.py`.

### Salesforce → Snowflake

Fetches Salesforce Analytics reports defined in `salesforce_config_public.py`, enriches ID columns with human-readable names via SOQL, and loads the results into Snowflake. Each report is written to both `FINANCE.SALESFORCE` (full load) and `FINANCE.BACKUP` (snapshot).

```bash
python salesforce_to_snowflake_public.py
```

Authentication uses JWT (private key). Set `SF_DOMAIN=test` in your `.env` to target a sandbox.

To add a new report, append a registry entry to `salesforce_config_public.py` — no pipeline code changes needed. Run once with `schema=None` then use `SHOW COLUMNS IN TABLE FINANCE.SALESFORCE.<TABLE>;` to discover column names for the schema definition.

### Azure Cost → Snowflake

Fetches Azure consumption data for the current month-to-date across configured subscriptions, writes to `FINANCE.PRODUCTION`.

```bash
python azure_cost_to_snowflake_public.py
```

### Deploy Semantic Views

Deploys YAML semantic model definitions to a target Snowflake database. Reads YAML files from `../semantic_layer/semantic_views/` and SQL staging views from `../semantic_layer/sql/staging/`.

```bash
# Validate YAML without deploying
python deploy_semantic_views_public.py --database ANALYTICS_DEV --verify-only

# Deploy to a database
python deploy_semantic_views_public.py --database ANALYTICS_DEV

# Deploy to production
python deploy_semantic_views_public.py --database ANALYTICS
```

The script will:
1. Create `SEMANTIC` and `STAGING` schemas if they don't exist
2. Deploy staging SQL views
3. Deploy semantic model YAML via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`
4. Grant access to roles listed in `SNOWFLAKE_GRANT_TO_ROLES`

Outputs GitHub Actions-compatible error annotations on failure.

---

## CI/CD (GitHub Actions)

Each pipeline has a corresponding workflow file. To activate them, copy them to `.github/workflows/` in your repo and add the required secrets under **Settings → Secrets and variables → Actions**.

### Required secrets per workflow

**All workflows:**
```
SNOWFLAKE_USER
SNOWFLAKE_ACCOUNT
SNOWFLAKE_PRIVATE_KEY_BASE64
SNOWFLAKE_WAREHOUSE
SNOWFLAKE_DATABASE
SNOWFLAKE_ROLE
```

**NetSuite** (`netsuite_to_snowflake_public.yaml`):
```
NS_REALM_ID
NS_COMPANY_ID
NS_CLIENT_KEY
NS_CLIENT_SECRET
NS_TOKEN_ID
NS_TOKEN_SECRET
```

**Salesforce** (`salesforce_to_snowflake_public.yaml`):
```
SF_USERNAME
SF_CONSUMER_KEY
SF_PRIVATE_KEY_BASE64
SF_DOMAIN
```

**Azure** (`azure_cost_to_snowflake_public.yaml`):
```
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_DEV_SUBSCRIPTION_ID
AZURE_PROD_SUBSCRIPTION_ID
```

All workflows use [Poetry](https://python-poetry.org/) for dependency management — ensure a `pyproject.toml` exists in the `snowflake/` directory.

---

## Data Architecture

```
Source APIs          Snowflake Schemas
─────────────        ─────────────────────────────────
NetSuite    ──────►  FINANCE.RAW          (raw ingest)
                     FINANCE.PRODUCTION   (clean tables)
                     FINANCE.BACKUP       (snapshots)

Salesforce  ──────►  FINANCE.PRODUCTION
                     FINANCE.BACKUP

Azure Costs ──────►  FINANCE.PRODUCTION

Semantic YAML ─────► {DATABASE}.SEMANTIC  (semantic views)
SQL Views   ──────►  {DATABASE}.STAGING   (staging views)
```

---

## Notes

- The NetSuite base URL is constructed dynamically from the `NS_COMPANY_ID` environment variable.
- The semantic model (`semantic_model_public.yml`) covers four tables: `SALESFORCE_OPPORTUNITIES`, `OPERATING_EXPENSES`, `CUSTOMER_REVENUE`, and `CLOUD_COST`.
