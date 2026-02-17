"""DuckDB storage layer."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl

from finance_core.utils.common import json_dumps

logger = logging.getLogger(__name__)


class FinanceDB:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            create table if not exists raw_statement_files (
              file_id varchar primary key,
              uploaded_at timestamp,
              source_type varchar,
              institution varchar,
              account_name varchar,
              account_last4 varchar,
              original_filename varchar,
              file_hash varchar unique,
              statement_start date,
              statement_end date,
              metadata_json varchar
            );
            create table if not exists raw_transactions (
              file_id varchar,
              row_id integer,
              raw_date timestamp,
              raw_posted_date timestamp,
              raw_description varchar,
              raw_amount double,
              raw_currency varchar,
              raw_balance double,
              raw_ref varchar,
              raw_json varchar
            );
            create table if not exists accounts (
              account_id varchar primary key,
              institution varchar,
              account_name varchar,
              account_last4 varchar,
              instrument_type varchar,
              notes varchar
            );
            create table if not exists txn_ledger (
              txn_id varchar primary key,
              fingerprint varchar unique,
              txn_date timestamp,
              posted_date timestamp,
              account_id varchar,
              instrument_type varchar,
              direction varchar,
              amount double,
              amount_signed double,
              currency varchar,
              description_raw varchar,
              description_norm varchar,
              merchant_clean varchar,
              merchant_group varchar,
              category varchar,
              category_source varchar,
              is_transfer boolean,
              transfer_group_id varchar,
              is_cc_payment boolean,
              cc_payment_group_id varchar,
              is_duplicate boolean,
              duplicate_group_id varchar,
              confidence double,
              flags_json varchar,
              raw_ref varchar,
              created_at timestamp,
              updated_at timestamp
            );
            create table if not exists merchant_overrides (
              pattern varchar,
              matcher_type varchar,
              merchant_clean varchar,
              merchant_group varchar,
              category varchar,
              updated_at timestamp
            );
            create table if not exists txn_overrides (
              txn_id varchar,
              merchant_clean varchar,
              category varchar,
              notes varchar,
              updated_at timestamp
            );
            """
        )

    def file_exists(self, file_hash: str) -> bool:
        return bool(self.conn.execute("select 1 from raw_statement_files where file_hash=?", [file_hash]).fetchone())

    def upsert_account(self, institution: str, account_name: str, account_last4: str, instrument_type: str) -> str:
        account_id = f"{institution}:{account_name}:{account_last4}:{instrument_type}"
        self.conn.execute(
            "insert into accounts values (?, ?, ?, ?, ?, ?) on conflict(account_id) do nothing",
            [account_id, institution, account_name, account_last4, instrument_type, ""],
        )
        return account_id

    def insert_raw_file(self, payload: dict) -> str:
        file_id = str(uuid4())
        self.conn.execute(
            """
            insert into raw_statement_files values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                file_id,
                datetime.utcnow(),
                payload["source_type"],
                payload.get("institution", "UNKNOWN"),
                payload.get("account_name", "PRIMARY"),
                payload.get("account_last4", "0000"),
                payload["original_filename"],
                payload["file_hash"],
                payload.get("statement_start"),
                payload.get("statement_end"),
                json_dumps(payload.get("metadata", {})),
            ],
        )
        return file_id

    def insert_raw_transactions(self, file_id: str, rows: list[dict]) -> None:
        for row in rows:
            self.conn.execute(
                "insert into raw_transactions values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    file_id,
                    row["row_id"],
                    row["txn_date"],
                    row.get("posted_date"),
                    row["description_raw"],
                    row["amount"],
                    row.get("currency", "INR"),
                    row.get("raw_balance"),
                    row.get("raw_ref"),
                    json.dumps(row.get("raw_json", {})),
                ],
            )

    def insert_ledger_rows(self, rows: list[dict]) -> int:
        inserted = 0
        for row in rows:
            try:
                self.conn.execute(
                    """
                    insert into txn_ledger values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        row["txn_id"],
                        row["fingerprint"],
                        row["txn_date"],
                        row.get("posted_date"),
                        row["account_id"],
                        row["instrument_type"],
                        row["direction"],
                        row["amount"],
                        row["amount_signed"],
                        row["currency"],
                        row["description_raw"],
                        row["description_norm"],
                        row["merchant_clean"],
                        row["merchant_group"],
                        row["category"],
                        row["category_source"],
                        row.get("is_transfer", False),
                        row.get("transfer_group_id"),
                        row.get("is_cc_payment", False),
                        row.get("cc_payment_group_id"),
                        row.get("is_duplicate", False),
                        row.get("duplicate_group_id"),
                        row.get("confidence", 0.5),
                        json_dumps(row.get("flags_json", [])),
                        row.get("raw_ref"),
                        row["created_at"],
                        row["updated_at"],
                    ],
                )
                inserted += 1
            except duckdb.ConstraintException:
                continue
        return inserted

    def ledger_df(self) -> pl.DataFrame:
        return self.conn.sql("select * from txn_ledger").pl()



    def get_txn_overrides(self) -> dict[str, dict]:
        rows = self.conn.execute(
            """
            select txn_id, merchant_clean, category, notes, updated_at
            from txn_overrides
            qualify row_number() over(partition by txn_id order by updated_at desc)=1
            """
        ).fetchall()
        return {
            r[0]: {"merchant_clean": r[1], "category": r[2], "notes": r[3], "updated_at": r[4]} for r in rows
        }

    def get_merchant_overrides(self) -> list[dict]:
        rows = self.conn.execute(
            """
            select pattern, matcher_type, merchant_clean, merchant_group, category, updated_at
            from merchant_overrides
            order by updated_at desc
            """
        ).fetchall()
        return [
            {
                "pattern": r[0],
                "matcher_type": r[1],
                "merchant_clean": r[2],
                "merchant_group": r[3],
                "category": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def upsert_merchant_override(
        self,
        pattern: str,
        matcher_type: str,
        merchant_clean: str,
        merchant_group: str,
        category: str,
    ) -> None:
        self.conn.execute(
            "insert into merchant_overrides values (?, ?, ?, ?, ?, ?)",
            [pattern, matcher_type, merchant_clean, merchant_group, category, datetime.utcnow()],
        )
    def update_txn_override(self, txn_id: str, merchant_clean: str, category: str, notes: str = "") -> None:
        self.conn.execute(
            "insert into txn_overrides values (?, ?, ?, ?, ?)",
            [txn_id, merchant_clean, category, notes, datetime.utcnow()],
        )
        self.conn.execute(
            "update txn_ledger set merchant_clean=?, category=?, category_source='MANUAL', updated_at=? where txn_id=?",
            [merchant_clean, category, datetime.utcnow(), txn_id],
        )
