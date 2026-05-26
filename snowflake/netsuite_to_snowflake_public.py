from __future__ import annotations

import os
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

from netsuite_helpers_public import (
    fetch_dataset,
    fetch_all_dataset_records,
    overwrite_df_to_snowflake,
    to_id_map,
    upsert_df_to_snowflake,
)
from netsuite_config_public import get_dataset_registry
from snowflake_connection_public import get_snowflake_connection, push_df_to_snowflake

load_dotenv()

NS_REALM_ID = os.getenv('NS_REALM_ID')
NS_COMPANY_ID = os.getenv('NS_COMPANY_ID')
NS_CLIENT_KEY = os.getenv('NS_CLIENT_KEY')
NS_CLIENT_SECRET = os.getenv('NS_CLIENT_SECRET')
NS_TOKEN_ID = os.getenv('NS_TOKEN_ID')
NS_TOKEN_SECRET = os.getenv('NS_TOKEN_SECRET')

conn = get_snowflake_connection()

netsuite_auth = OAuth1(
    client_key=NS_CLIENT_KEY,
    client_secret=NS_CLIENT_SECRET,
    resource_owner_key=NS_TOKEN_ID,
    resource_owner_secret=NS_TOKEN_SECRET,
    signature_method='HMAC-SHA256',
    signature_type='AUTH_HEADER',
    realm=NS_REALM_ID,
)

accounts = fetch_all_dataset_records(netsuite_auth, dataset_id="example_accounts")
periods = fetch_all_dataset_records(netsuite_auth, dataset_id="example_periods")
depts = fetch_all_dataset_records(netsuite_auth, dataset_id="example_departments")
customers = fetch_all_dataset_records(netsuite_auth, dataset_id="example_customers")
vendors = fetch_all_dataset_records(netsuite_auth, dataset_id="example_vendors")

account_map = to_id_map(accounts, value_key="displayname")
period_map = to_id_map(periods, value_key="periodname")
dept_map = to_id_map(depts, value_key="name")
customer_map = to_id_map(customers, value_key="companyname")
vendor_map = to_id_map(vendors, value_key="companyname")

registry = get_dataset_registry(account_map, period_map, dept_map, customer_map, vendor_map)

try:
    fetched = {}
    for config in registry:
        df = fetch_dataset(netsuite_auth, config)
        fetched[config["table_name"]] = df
        if config.get("load_mode") == "overwrite":
            overwrite_df_to_snowflake(conn, df, config["table_name"], schema=config.get("schema"))
        else:
            upsert_df_to_snowflake(conn, df, config["table_name"], id_col=config["id_col"], schema=config.get("schema"))

    for config in registry:
        push_df_to_snowflake(conn, fetched[config["table_name"]], config["table_name"], schema=config.get("schema"), snapshot=True)
finally:
    conn.close()
