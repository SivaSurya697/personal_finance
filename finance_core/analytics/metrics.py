"""Analytics and reporting views."""
from __future__ import annotations

import polars as pl


def expense_view(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(
        (pl.col("direction") == "outflow")
        & (~pl.col("is_duplicate"))
        & (~pl.col("is_transfer"))
        & (~pl.col("is_cc_payment"))
    )


def cashflow_outflow_view(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter((pl.col("direction") == "outflow") & (~pl.col("is_duplicate")))


def category_summary(df: pl.DataFrame) -> pl.DataFrame:
    return df.group_by("category").agg(pl.col("amount").sum().alias("spend")).sort("spend", descending=True)


def monthly_trend(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    return (
        df.with_columns(pl.col("txn_date").dt.strftime("%Y-%m").alias("month"))
        .group_by("month")
        .agg(pl.col("amount").sum().alias("total"))
        .sort("month")
    )
