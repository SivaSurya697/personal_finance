from __future__ import annotations

from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from finance_core.ingestion.pipeline import IngestionService
from finance_core.storage.db import FinanceDB

st.title("Data Quality")
db = FinanceDB(Path("data/db/finance.duckdb"))
ing = IngestionService(db, Path("rules"))
df = db.ledger_df()
if df.is_empty():
    st.info("No data")
else:
    st.metric("Duplicates", int(df.filter(df["is_duplicate"]).height))
    st.metric("Transfers", int(df.filter(df["is_transfer"]).height))
    st.metric("CC Payments", int(df.filter(df["is_cc_payment"]).height))
    st.subheader("Circular flow flags")
    circ = df.filter(df["flags_json"].str.contains("CIRCULAR_FLOW"))
    st.dataframe(circ.to_pandas(), use_container_width=True)
    st.subheader("Uncategorized")
    unc = df.filter(df["category"] == "Uncategorized")
    st.dataframe(unc.to_pandas(), use_container_width=True)

    st.subheader("Edit transaction override")
    txns = df.select(["txn_id", "description_raw", "merchant_clean", "category"]).to_dicts()
    options = [f"{t['txn_id']} | {t['description_raw'][:60]}" for t in txns]
    sel = st.selectbox("Transaction", options=options)
    tid = sel.split(" | ")[0]
    current = next(t for t in txns if t["txn_id"] == tid)
    merchant = st.text_input("Merchant clean", value=current["merchant_clean"] or "")
    category = st.text_input("Category", value=current["category"] or "")
    if st.button("Save override and recompute"):
        db.update_txn_override(tid, merchant, category)
        ing.refresh_matching()
        st.success("Override saved and matching refreshed.")
