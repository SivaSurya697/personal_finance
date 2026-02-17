from __future__ import annotations

from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
import streamlit as st

from finance_core.analytics.metrics import monthly_trend
from finance_core.storage.db import FinanceDB

st.title("History")
db = FinanceDB(Path("data/db/finance.duckdb"))
df = db.ledger_df()
if df.is_empty():
    st.info("No data")
else:
    trend = monthly_trend(df)
    st.line_chart(trend.to_pandas().set_index("month"))
    st.dataframe(trend.to_pandas(), use_container_width=True)

    st.subheader("Recurring detector (monthly cadence)")
    rec = (
        df.with_columns(pl.col("txn_date").dt.strftime("%Y-%m").alias("month"))
        .group_by(["merchant_clean", "month"]) 
        .agg(pl.col("amount").mean().alias("amt"), pl.len().alias("cnt"))
        .group_by("merchant_clean")
        .agg(pl.len().alias("months"), pl.col("amt").std().fill_null(0).alias("amt_std"))
        .filter((pl.col("months") >= 2) & (pl.col("amt_std") <= 100))
        .sort("months", descending=True)
    )
    st.dataframe(rec.to_pandas(), use_container_width=True)
