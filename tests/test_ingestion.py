from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("polars")
pytest.importorskip("yaml")

import polars as pl

from finance_core.analytics.metrics import expense_view
from finance_core.ingestion.pipeline import IngestionService
from finance_core.matching.linking import mark_cc_payments, mark_duplicates
from finance_core.storage.db import FinanceDB


def test_fingerprint_idempotent_ingestion(tmp_path: Path):
    db = FinanceDB(tmp_path / "finance.duckdb")
    rules = Path("rules")
    ing = IngestionService(db, rules)

    stmt = tmp_path / "bank.txt"
    stmt.write_text(
        "Date,Narration,Value Dat,Debit Amount,Credit Amount,Chq/Ref Number,Closing Balance\n"
        "01/02/26,UPI-APPLE,01/02/26,219.00,0.00,001,1000\n",
        encoding="utf-8",
    )

    r1 = ing.ingest_file(stmt)
    r2 = ing.ingest_file(stmt)
    assert r1["skipped"] is False
    assert r2["skipped"] is True
    assert db.ledger_df().height == 1


def test_dedupe_keeps_cgst_sgst(tmp_path: Path):
    db = FinanceDB(tmp_path / "finance.duckdb")
    now_df = db.conn.sql("""
        select * from (values
        ('1','f1','2026-02-01'::timestamp,null,'a','credit','outflow',10.0,-10.0,'INR','CGST FEE','CGST FEE','M','M','Fees/Taxes','HEURISTIC',false,null,false,null,false,null,0.8,'[]',null,now(),now()),
        ('2','f2','2026-02-01'::timestamp,null,'a','credit','outflow',10.0,-10.0,'INR','SGST FEE','SGST FEE','M','M','Fees/Taxes','HEURISTIC',false,null,false,null,false,null,0.8,'[]',null,now(),now())
        ) as t(txn_id,fingerprint,txn_date,posted_date,account_id,instrument_type,direction,amount,amount_signed,currency,description_raw,description_norm,merchant_clean,merchant_group,category,category_source,is_transfer,transfer_group_id,is_cc_payment,cc_payment_group_id,is_duplicate,duplicate_group_id,confidence,flags_json,raw_ref,created_at,updated_at)
    """).pl()
    out = mark_duplicates(now_df)
    assert out["is_duplicate"].sum() == 0


def test_near_duplicate_marking():
    df = pl.DataFrame(
        {
            "txn_id": ["1", "2"],
            "account_id": ["a", "a"],
            "txn_date": [__import__("datetime").datetime(2026, 2, 1), __import__("datetime").datetime(2026, 2, 2)],
            "amount": [100.0, 100.0],
            "description_norm": ["KFC ORDER", "KFC ORDER AGAIN"],
            "raw_ref": [None, None],
            "merchant_clean": ["KFC", "KFC"],
        }
    ).with_columns(pl.col("txn_date").cast(pl.Datetime))
    out = mark_duplicates(df, near_days=2)
    assert out.filter(pl.col("txn_id") == "2")["is_duplicate"][0] is True


def test_expense_view_excludes_cc_and_transfer(tmp_path: Path):
    db = FinanceDB(tmp_path / "finance.duckdb")
    db.conn.execute("""
      insert into txn_ledger values
      ('1','a','2026-02-01',null,'x','credit','outflow',100,-100,'INR','KFC','KFC','KFC','KFC','Food','RULE',false,null,false,null,false,null,0.9,'[]',null,now(),now()),
      ('2','b','2026-02-02',null,'y','debit','outflow',100,-100,'INR','CREDIT CARD PAYMENT','CREDIT CARD PAYMENT','BANK','BANK','CC Payment','HEURISTIC',false,null,true,'grp',false,null,0.9,'[]',null,now(),now()),
      ('3','c','2026-02-02',null,'y','debit','outflow',100,-100,'INR','TRANSFER TO SELF','TRANSFER TO SELF','SELF','SELF','Transfers','HEURISTIC',true,'g',false,null,false,null,0.9,'[]',null,now(),now())
    """)
    ev = expense_view(db.ledger_df())
    assert ev.height == 1
    assert ev["txn_id"][0] == "1"


def test_cc_payment_assigns_group_id():
    df = pl.DataFrame(
        {
            "txn_id": ["1", "2"],
            "description_norm": ["CREDIT CARD PAYMENT", "KFC"],
            "category": ["Transfers", "Food"],
            "instrument_type": ["debit", "credit"],
            "direction": ["outflow", "outflow"],
            "amount": [500.0, 500.0],
            "txn_date": [__import__("datetime").datetime(2026, 2, 5), __import__("datetime").datetime(2026, 2, 2)],
            "account_id": ["bank", "cc"],
            "is_duplicate": [False, False],
        }
    ).with_columns(pl.col("txn_date").cast(pl.Datetime))
    out = mark_cc_payments(df, ["CREDIT CARD"])
    row = out.filter(pl.col("txn_id") == "1").to_dicts()[0]
    assert row["is_cc_payment"] is True
    assert row["cc_payment_group_id"] is not None


def test_override_precedence_txn_overrides(tmp_path: Path):
    db = FinanceDB(tmp_path / "finance.duckdb")
    ing = IngestionService(db, Path("rules"))
    db.conn.execute("""
      insert into txn_ledger values
      ('1','a','2026-02-01',null,'x','debit','outflow',100,-100,'INR','ABC','ABC','ABC','ABC','Uncategorized','HEURISTIC',false,null,false,null,false,null,0.5,'[]',null,now(),now())
    """)
    db.upsert_merchant_override("ABC", "contains", "M1", "G1", "Food")
    db.update_txn_override("1", "M2", "Travel")
    ing.refresh_matching()
    row = db.conn.execute("select merchant_clean, category, category_source from txn_ledger where txn_id='1'").fetchone()
    assert row[0] == "M2"
    assert row[1] == "Travel"
    assert row[2] == "MANUAL"
