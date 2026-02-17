from __future__ import annotations

from pathlib import Path

import polars as pl
import streamlit as st

from finance_core.analytics.metrics import cashflow_outflow_view, expense_view
from finance_core.ingestion.pipeline import IngestionService
from finance_core.storage.db import FinanceDB

st.set_page_config(page_title="Personal Finance Dashboard", layout="wide")

DB_PATH = Path("data/db/finance.duckdb")
RULES_DIR = Path("rules")
UPLOADS = Path("data/uploads")
UPLOADS.mkdir(parents=True, exist_ok=True)


@st.cache_resource
def get_services():
    db = FinanceDB(DB_PATH)
    ing = IngestionService(db, RULES_DIR)
    return db, ing


db, ingestion = get_services()

st.title("Local-first Personal Finance Dashboard")

uploaded = st.sidebar.file_uploader("Upload statements", type=["csv", "txt"], accept_multiple_files=True)
mode = st.sidebar.radio("View mode", ["Expense", "Cashflow"])

if uploaded:
    for f in uploaded:
        dest = UPLOADS / f.name
        dest.write_bytes(f.read())
        res = ingestion.ingest_file(dest)
        st.sidebar.write(res)

ledger = db.ledger_df()
if ledger.is_empty():
    st.info("Upload statements to begin.")
else:
    dmin = ledger["txn_date"].min().date()
    dmax = ledger["txn_date"].max().date()
    dr = st.sidebar.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
    accounts = sorted(ledger["account_id"].unique().to_list())
    selected_accounts = st.sidebar.multiselect("Accounts", options=accounts, default=accounts)

    filtered = ledger
    if isinstance(dr, tuple) and len(dr) == 2:
        start, end = dr
        filtered = filtered.filter((pl.col("txn_date") >= pl.lit(start)) & (pl.col("txn_date") <= pl.lit(end)))
    if selected_accounts:
        filtered = filtered.filter(pl.col("account_id").is_in(selected_accounts))

    view = expense_view(filtered) if mode == "Expense" else cashflow_outflow_view(filtered)
    st.metric("Rows in view", view.height)
    st.dataframe(view.to_pandas(), use_container_width=True)
