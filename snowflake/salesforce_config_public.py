from __future__ import annotations

# ---------------------------------------------------------------------------
# REPORT REGISTRY
#
# Each entry defines everything needed to fetch, transform, and load one
# Salesforce Analytics report into Snowflake.
#
# Keys:
#   report_id      – Salesforce Analytics report ID
#   table_name     – Snowflake target table (FINANCE.SALESFORCE)
#   rename_cols    – {source_col: target_col} applied after flattening.
#                    Used to rename columns that contain raw Salesforce IDs
#                    so their original names are freed up for the resolved
#                    human-readable names produced by the enrichment step.
#   object_mapping – List of enrichment specs passed to enrich_dataframe().
#                    Each spec must include:
#                      "object"     – Salesforce SObject name
#                      "id_columns" – columns to gather IDs from
#                      "targets"    – list of (id_col, name_col) tuples
#   schema         – Optional list of (col_name, type) tuples controlling
#                    exactly which columns are written to Snowflake, in what
#                    order, and with what types (STRING / FLOAT / INTEGER /
#                    BOOLEAN / DATE / TIMESTAMP). When None, column types are
#                    inferred heuristically. Always include ("loaded_at",
#                    "TIMESTAMP") as the last entry.
#                    To discover column names: run the pipeline once with
#                    schema=None, then query Snowflake:
#                      SHOW COLUMNS IN TABLE FINANCE.SALESFORCE.<TABLE_NAME>;
#
# To add a new Salesforce report in the future, append one dict here.
# No changes to pipeline code are required.
# ---------------------------------------------------------------------------

REPORT_REGISTRY = [
    {
        "report_id": "YOUR_REPORT_ID_HERE",
        "table_name": "SALESFORCE_OPPORTUNITIES",
        "rename_cols": {
            "account_name": "account_id",
            "account_owner": "account_owner_id",
            "parent_account": "parent_account_id",
        },
        "object_mapping": [
            {
                "object": "Account",
                "id_columns": ["account_id", "parent_account_id"],
                "targets": [
                    ("account_id", "account_name"),
                    ("parent_account_id", "parent_account"),
                ],
            },
            {
                "object": "User",
                "id_columns": ["account_owner_id"],
                "targets": [("account_owner_id", "account_owner")],
            },
        ],
        # Populate after first run: SHOW COLUMNS IN TABLE FINANCE.SALESFORCE.SALESFORCE_TAM;
        "schema": [
            ("account_id",                          "STRING"),
            ("account_owner_id",                    "STRING"),
            ("parent_account_id",                   "STRING"),
            ("type",                                "STRING"),
            ("account_segment",                     "STRING"),
            ("billing_state_province_text_only",    "STRING"),
            ("last_activity_date",                  "DATE"),
            ("account_id_18",                       "STRING"),
            ("account_name",                        "STRING"),
            ("parent_account",                      "STRING"),
            ("account_owner",                       "STRING"),
            ("loaded_at",                           "TIMESTAMP"),
        ],
    },
    {
        "report_id": "YOUR_REPORT_ID_HERE",
        "table_name": "SALESFORCE_UNIVERSAL_CUSTOMER",
        "rename_cols": {
            "account_owner": "account_owner_id",
            "partner_success_rep": "partner_success_rep_id",
            "implementation_manager": "implementation_manager_id",
        },
        "object_mapping": [
            {
                "object": "User",
                "id_columns": [
                    "account_owner_id",
                    "partner_success_rep_id",
                    "implementation_manager_id",
                ],
                "targets": [
                    ("account_owner_id", "account_owner"),
                    ("partner_success_rep_id", "partner_success_rep"),
                    ("implementation_manager_id", "implementation_manager"),
                ],
            },
            {
                "object": "Account",
                "id_columns": ["account_id_18"],
                "targets": [("account_id_18", "account_name")],
            },
        ],
        # Populate after first run: SHOW COLUMNS IN TABLE FINANCE.SALESFORCE.SALESFORCE_UNIVERSAL_CUSTOMER;
        "schema": [
            ("account_id_18",               "STRING"),
            ("org_id",                      "STRING"),
            ("account_owner_id",            "STRING"),
            ("partner_success_rep_id",      "STRING"),
            ("implementation_manager_id",   "STRING"),
            ("customer_health",             "STRING"),
            ("account_status",              "STRING"),
            ("account_segment",             "STRING"),
            ("implementation_status_f",     "STRING"),
            ("account_name",                "STRING"),
            ("account_owner",               "STRING"),
            ("partner_success_rep",         "STRING"),
            ("implementation_manager",      "STRING"),
            ("loaded_at",                   "TIMESTAMP"),
        ],
    },
]
