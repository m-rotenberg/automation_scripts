from __future__ import annotations


def get_dataset_registry(account_map, period_map, dept_map, customer_map, vendor_map):
    return [
        {
            "dataset_id": "example_dataset_1",
            "table_name": "OPERATING_EXPENSES",
            "id_col": "unique_id",
            "strip_custrecord_prefix": False,
            "rename_cols": {
                "formula_1": "entity_name",
                "formula_2": "rollup",
                "formula_3": "employee",
                "formula_4": "unique_id",
                "custrecord_group": "group_name",
            },
            "lookup_cols": {
                "account": account_map,
                "postingperiod": period_map,
                "department": dept_map,
            },
            "drop_cols": ["links", "entity"],
            "schema": [
                ("account", "STRING"),
                ("amount", "FLOAT"),
                ("department", "STRING"),
                ("postingperiod", "STRING"),
                ("trandate", "DATE"),
                ("type", "STRING"),
                ("employee", "STRING"),
                ("unique_id", "STRING"),
            ],
        },
        {
            "dataset_id": "example_dataset_2",
            "table_name": "CUSTOMER_REVENUE",
            "id_col": "id",
            "strip_custrecord_prefix": True,
            "rename_cols": {},
            "lookup_cols": {},
            "drop_cols": ["links"],
            "schema": [
                ("companyname", "STRING"),
                ("revenue", "FLOAT"),
                ("customer_id", "STRING"),
                ("id", "STRING"),
                ("external_id", "STRING"),
            ],
        },
    ]
