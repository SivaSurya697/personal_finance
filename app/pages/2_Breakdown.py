from __future__ import annotations

from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
import streamlit as st

from finance_core.analytics.metrics import category_summary, expense_view
from finance_core.storage.db import FinanceDB

st.title("Breakdown")
db = FinanceDB(Path("data/db/finance.duckdb"))
df = db.ledger_df()
if df.is_empty():
    st.info("No data")
else:
    exp = expense_view(df)
    cat = category_summary(exp)
    st.bar_chart(cat.to_pandas().set_index("category"))

    cats = sorted(exp["category"].unique().to_list())
    sel = st.selectbox("Drilldown category", options=["All"] + cats)
    view = exp if sel == "All" else exp.filter(pl.col("category") == sel)
    merchant = (
        view.group_by("merchant_clean")
        .agg(pl.col("amount").sum().alias("spend"))
        .sort("spend", descending=True)
    )
    st.subheader("Merchant drilldown")
    st.dataframe(merchant.to_pandas(), use_container_width=True)
    st.dataframe(view.to_pandas(), use_container_width=True)
