"""Duplicate, transfer, cc-payment, and circular-flow matching."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from uuid import uuid4

import polars as pl


def mark_duplicates(df: pl.DataFrame, near_days: int = 2) -> pl.DataFrame:
    """Mark exact and near duplicates while preserving tax split lines."""
    if df.is_empty():
        return df

    rows = sorted(df.to_dicts(), key=lambda r: (r["txn_date"], r["account_id"], r["amount"]))
    marks: dict[str, str] = {}

    # Exact duplicates
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            row["account_id"],
            row["txn_date"].date(),
            round(float(row["amount"]), 2),
            row.get("description_norm", ""),
            row.get("raw_ref") or "",
        )
        buckets[key].append(row)

    for grouped in buckets.values():
        if len(grouped) <= 1:
            continue
        desc = (grouped[0].get("description_norm") or "").upper()
        if "CGST" in desc or "SGST" in desc:
            continue
        gid = str(uuid4())
        for dupe in grouped[1:]:
            marks[dupe["txn_id"]] = gid

    # Near duplicates: same merchant+amount within window, same account
    by_account = defaultdict(list)
    for row in rows:
        by_account[row["account_id"]].append(row)

    for account_rows in by_account.values():
        for i, left in enumerate(account_rows):
            if left["txn_id"] in marks:
                continue
            left_desc = (left.get("description_norm") or "").upper()
            if "CGST" in left_desc or "SGST" in left_desc:
                continue
            for right in account_rows[i + 1 :]:
                if right["txn_id"] in marks:
                    continue
                if abs((left["txn_date"] - right["txn_date"]).days) > near_days:
                    if right["txn_date"] > left["txn_date"] + timedelta(days=near_days):
                        break
                    continue
                if round(float(left["amount"]), 2) != round(float(right["amount"]), 2):
                    continue
                if (left.get("merchant_clean") or "") != (right.get("merchant_clean") or ""):
                    continue
                rdesc = (right.get("description_norm") or "").upper()
                if "CGST" in rdesc or "SGST" in rdesc:
                    continue
                gid = str(uuid4())
                marks[right["txn_id"]] = gid

    return df.with_columns(
        pl.col("txn_id").map_elements(lambda x: x in marks, return_dtype=pl.Boolean).alias("is_duplicate"),
        pl.col("txn_id").map_elements(lambda x: marks.get(x), return_dtype=pl.Utf8).alias("duplicate_group_id"),
    )


def mark_transfers(df: pl.DataFrame, amount_tolerance: float = 5, day_window: int = 1) -> pl.DataFrame:
    if df.is_empty():
        return df
    rows = df.to_dicts()
    marks: dict[str, str] = {}
    for i, a in enumerate(rows):
        if a["direction"] != "outflow":
            continue
        for b in rows[i + 1 :]:
            if b["direction"] != "inflow" or a["account_id"] == b["account_id"]:
                continue
            if abs(a["amount"] - b["amount"]) <= amount_tolerance and abs((a["txn_date"] - b["txn_date"]).days) <= day_window:
                gid = marks.get(a["txn_id"]) or marks.get(b["txn_id"]) or str(uuid4())
                marks[a["txn_id"]] = gid
                marks[b["txn_id"]] = gid

    return df.with_columns(
        pl.col("txn_id").map_elements(lambda x: x in marks, return_dtype=pl.Boolean).alias("is_transfer"),
        pl.col("txn_id").map_elements(lambda x: marks.get(x), return_dtype=pl.Utf8).alias("transfer_group_id"),
    )


def mark_cc_payments(df: pl.DataFrame, keywords: list[str], amount_tolerance: float = 50.0) -> pl.DataFrame:
    """Keyword mark CC payments and best-effort link to a credit account-month spend cluster."""
    kws = [k.upper() for k in keywords]
    out = df.with_columns(
        pl.col("description_norm").map_elements(lambda x: any(k in (x or "") for k in kws), return_dtype=pl.Boolean).alias("is_cc_payment")
    )

    rows = out.to_dicts()
    cc_group: dict[str, str] = {}

    monthly_credit = defaultdict(float)
    for r in rows:
        if r.get("instrument_type") == "credit" and r.get("direction") == "outflow" and not r.get("is_duplicate"):
            month = r["txn_date"].strftime("%Y-%m")
            monthly_credit[(r["account_id"], month)] += float(r["amount"])

    for r in rows:
        if not r.get("is_cc_payment") or r.get("instrument_type") != "debit":
            continue
        month = r["txn_date"].strftime("%Y-%m")
        amt = float(r["amount"])
        best_key = None
        best_diff = float("inf")
        for (acc, m), total in monthly_credit.items():
            if m not in {month, (r["txn_date"] - timedelta(days=31)).strftime("%Y-%m"), (r["txn_date"] + timedelta(days=31)).strftime("%Y-%m")}:
                continue
            diff = abs(total - amt)
            if diff < best_diff:
                best_diff = diff
                best_key = (acc, m)
        if best_key and best_diff <= amount_tolerance:
            cc_group[r["txn_id"]] = f"CCPAY:{best_key[0]}:{best_key[1]}"
        else:
            cc_group[r["txn_id"]] = f"CCPAY:UNLINKED:{month}:{int(amt)}"

    return out.with_columns(
        pl.when(pl.col("is_cc_payment")).then(pl.lit("CC Payment")).otherwise(pl.col("category")).alias("category"),
        pl.col("txn_id").map_elements(lambda x: cc_group.get(x), return_dtype=pl.Utf8).alias("cc_payment_group_id"),
    )


def flag_circular_flows(df: pl.DataFrame, window_days: int = 14) -> pl.DataFrame:
    """Detect cycles in transfer graph in a rolling window."""
    rows = df.to_dicts()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        gid = r.get("transfer_group_id")
        if r.get("is_transfer") and gid:
            grouped[gid].append(r)

    edges: list[tuple[str, str, str, object]] = []
    for gid, txns in grouped.items():
        outflow = next((x for x in txns if x["direction"] == "outflow"), None)
        inflow = next((x for x in txns if x["direction"] == "inflow"), None)
        if outflow and inflow:
            d = min(outflow["txn_date"], inflow["txn_date"])
            edges.append((outflow["account_id"], inflow["account_id"], gid, d))

    flags: dict[str, list[str]] = defaultdict(list)
    for src, dst, gid, d in edges:
        for src2, dst2, gid2, d2 in edges:
            if dst != src2:
                continue
            for src3, dst3, gid3, d3 in edges:
                if dst2 == src and src3 == dst3:
                    continue
                if dst2 == src3 and dst3 == src:
                    min_d = min(d, d2, d3)
                    max_d = max(d, d2, d3)
                    if (max_d - min_d).days <= window_days:
                        for cg in {gid, gid2, gid3}:
                            for txn in grouped[cg]:
                                flags[txn["txn_id"]].append("CIRCULAR_FLOW")

    return df.with_columns(
        pl.col("txn_id").map_elements(lambda x: sorted(set(flags.get(x, []))), return_dtype=pl.List(pl.Utf8)).alias("flags_json")
    )
