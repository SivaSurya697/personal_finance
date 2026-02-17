from __future__ import annotations

from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from finance_core.analytics.metrics import category_summary, expense_view
from finance_core.rules.engine import RuleEngine
from finance_core.storage.db import FinanceDB

st.title("Control Tower")
db = FinanceDB(Path("data/db/finance.duckdb"))
engine = RuleEngine(Path("rules"))
df = db.ledger_df()
if df.is_empty():
    st.info("No data")
else:
    exp = expense_view(df)
    mtd = float(exp["amount"].sum()) if exp.height else 0.0
    st.metric("MTD Spend", f"₹{mtd:,.2f}")

    budgets = engine.config.get("budgets", {})
    total_budget = float(sum(budgets.values())) if budgets else 0.0
    st.metric("Budget Remaining", f"₹{(total_budget - mtd):,.2f}")

    st.subheader("Top Categories")
    st.dataframe(category_summary(exp).to_pandas(), use_container_width=True)

    st.subheader("Alerts")
    if total_budget and mtd > total_budget:
        st.warning("Overspend alert: month-to-date spend exceeds configured total budget.")

    new_merchant_count = exp.filter(exp["category_source"] != "RULE").height
    if new_merchant_count:
        st.info(f"{new_merchant_count} transactions are heuristic/manual categorized; review for new merchants.")

    if exp.height:
        threshold = float(exp["amount"].quantile(0.95))
        unusual = exp.filter(exp["amount"] >= threshold)
        if unusual.height:
            st.error(f"Unusual large transactions detected: {unusual.height}")
