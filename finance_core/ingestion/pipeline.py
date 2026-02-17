"""Ingestion orchestrator from file -> raw -> canonical ledger."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from finance_core.ingestion.parsers import BankTxtStatementParser, DelimitedCardStatementParser, ParserRegistry
from finance_core.matching.linking import flag_circular_flows, mark_cc_payments, mark_duplicates, mark_transfers
from finance_core.normalize.transformers import build_fingerprint, extract_merchant, normalize_description
from finance_core.rules.engine import RuleEngine
from finance_core.storage.db import FinanceDB
from finance_core.utils.common import sha256_file

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, db: FinanceDB, rules_dir: Path):
        self.db = db
        self.rule_engine = RuleEngine(rules_dir)
        self.registry = ParserRegistry([DelimitedCardStatementParser(), BankTxtStatementParser()])

    def ingest_file(
        self,
        path: Path,
        institution: str = "LOCAL",
        account_name: str = "PRIMARY",
        account_last4: str = "0000",
    ) -> dict:
        file_hash = sha256_file(path)
        if self.db.file_exists(file_hash):
            return {"file": path.name, "skipped": True, "reason": "duplicate_file_hash"}

        parsed = self.registry.parse(path)
        file_id = self.db.insert_raw_file(
            {
                "source_type": parsed.source_type_guess,
                "institution": institution,
                "account_name": account_name,
                "account_last4": account_last4,
                "original_filename": path.name,
                "file_hash": file_hash,
                "metadata": parsed.metadata,
            }
        )
        self.db.insert_raw_transactions(file_id, parsed.rows)
        account_id = self.db.upsert_account(institution, account_name, account_last4, parsed.instrument_type)

        now = datetime.utcnow()
        ledger_rows = []
        for row in parsed.rows:
            desc_norm = normalize_description(row["description_raw"])
            merchant_clean, merchant_group = extract_merchant(desc_norm)
            merchant_clean, merchant_group, category, source, confidence = self.rule_engine.apply(desc_norm, merchant_clean)
            signed = -row["amount"] if row["direction"] == "outflow" else row["amount"]
            fingerprint = build_fingerprint(
                account_id=account_id,
                txn_date=row["txn_date"],
                amount=row["amount"],
                direction=row["direction"],
                description_norm=desc_norm,
                raw_ref=row.get("raw_ref"),
            )
            ledger_rows.append(
                {
                    "txn_id": str(uuid4()),
                    "fingerprint": fingerprint,
                    "txn_date": row["txn_date"],
                    "posted_date": row.get("posted_date"),
                    "account_id": account_id,
                    "instrument_type": parsed.instrument_type,
                    "direction": row["direction"],
                    "amount": row["amount"],
                    "amount_signed": signed,
                    "currency": row.get("currency", "INR"),
                    "description_raw": row["description_raw"],
                    "description_norm": desc_norm,
                    "merchant_clean": merchant_clean,
                    "merchant_group": merchant_group,
                    "category": category,
                    "category_source": source,
                    "is_transfer": False,
                    "transfer_group_id": None,
                    "is_cc_payment": False,
                    "cc_payment_group_id": None,
                    "is_duplicate": False,
                    "duplicate_group_id": None,
                    "confidence": confidence,
                    "flags_json": row.get("flags", []),
                    "raw_ref": row.get("raw_ref"),
                    "created_at": now,
                    "updated_at": now,
                }
            )

        self.db.insert_ledger_rows(ledger_rows)
        self.refresh_matching()
        return {"file": path.name, "skipped": False, "file_id": file_id, "inserted": len(parsed.rows)}

    def _apply_overrides(self) -> None:
        # merchant overrides first
        merchant_overrides = self.db.get_merchant_overrides()
        for mo in merchant_overrides:
            patt = mo.get("pattern") or ""
            if not patt:
                continue
            matcher = (mo.get("matcher_type") or "contains").lower()
            all_rows = self.db.conn.execute("select txn_id, description_norm from txn_ledger").fetchall()
            for txn_id, desc in all_rows:
                desc = desc or ""
                hit = False
                if matcher == "regex":
                    hit = re.search(patt, desc, flags=re.IGNORECASE) is not None
                else:
                    hit = patt.upper() in desc.upper()
                if hit:
                    self.db.conn.execute(
                        """
                        update txn_ledger
                        set merchant_clean=?, merchant_group=?, category=?, category_source='MANUAL', updated_at=?
                        where txn_id=?
                        """,
                        [mo.get("merchant_clean"), mo.get("merchant_group"), mo.get("category"), datetime.utcnow(), txn_id],
                    )

        # txn overrides highest precedence
        txn_overrides = self.db.get_txn_overrides()
        for txn_id, ov in txn_overrides.items():
            self.db.conn.execute(
                """
                update txn_ledger
                set merchant_clean=?, category=?, category_source='MANUAL', updated_at=?
                where txn_id=?
                """,
                [ov.get("merchant_clean"), ov.get("category"), datetime.utcnow(), txn_id],
            )

    def refresh_matching(self) -> None:
        df = self.db.ledger_df()
        if df.is_empty():
            return
        cfg = self.rule_engine.config
        dedupe_days = cfg.get("dedupe", {}).get("near_date_window_days", 2)
        transfer_tol = cfg.get("transfer", {}).get("amount_tolerance", 5)
        transfer_days = cfg.get("transfer", {}).get("date_window_days", 1)
        circular_days = cfg.get("circular", {}).get("window_days", 14)
        cc_keywords = cfg.get("keywords", {}).get("cc_payment", ["CREDIT CARD", "CARD PAYMENT", "CC PAYMENT", "CARD BILL"])

        df2 = mark_duplicates(df, near_days=dedupe_days)
        df2 = mark_transfers(df2, amount_tolerance=transfer_tol, day_window=transfer_days)
        df2 = mark_cc_payments(df2, cc_keywords)
        df2 = flag_circular_flows(df2, window_days=circular_days)

        self.db.conn.execute(
            """
            update txn_ledger set
              is_duplicate=false, duplicate_group_id=null,
              is_transfer=false, transfer_group_id=null,
              is_cc_payment=false, cc_payment_group_id=null,
              flags_json='[]'
        """
        )
        for row in df2.select(
            [
                "txn_id",
                "is_duplicate",
                "duplicate_group_id",
                "is_transfer",
                "transfer_group_id",
                "is_cc_payment",
                "cc_payment_group_id",
                "category",
                "flags_json",
            ]
        ).to_dicts():
            self.db.conn.execute(
                """
                update txn_ledger
                set is_duplicate=?, duplicate_group_id=?, is_transfer=?, transfer_group_id=?, is_cc_payment=?, cc_payment_group_id=?, category=?, flags_json=?, updated_at=?
                where txn_id=?
                """,
                [
                    row.get("is_duplicate", False),
                    row.get("duplicate_group_id"),
                    row.get("is_transfer", False),
                    row.get("transfer_group_id"),
                    row.get("is_cc_payment", False),
                    row.get("cc_payment_group_id"),
                    row.get("category"),
                    str(row.get("flags_json", [])),
                    datetime.utcnow(),
                    row["txn_id"],
                ],
            )
        self._apply_overrides()
