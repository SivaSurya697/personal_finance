"""Core models for personal finance ingestion and ledger pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ParsedStatement:
    """Normalized parser output prior to raw persistence."""

    metadata: dict[str, Any]
    rows: list[dict[str, Any]]
    source_type_guess: str
    instrument_type: str
    account_hint: str | None = None


@dataclass(slots=True)
class ParsedFile:
    """Container for a parsed file plus source path."""

    path: Path
    parsed: ParsedStatement


@dataclass(slots=True)
class IngestionResult:
    """Summary for an ingestion operation."""

    file_id: str
    file_hash: str
    inserted_raw_rows: int
    inserted_ledger_rows: int
    skipped_as_duplicate_file: bool = False


@dataclass(slots=True)
class LedgerTransaction:
    """Canonical transaction record with lifecycle fields."""

    txn_id: str
    fingerprint: str
    txn_date: datetime
    posted_date: datetime | None
    account_id: str
    instrument_type: str
    direction: str
    amount: float
    amount_signed: float
    currency: str
    description_raw: str
    description_norm: str
    merchant_clean: str
    merchant_group: str
    category: str
    category_source: str
    is_transfer: bool
    transfer_group_id: str | None
    is_cc_payment: bool
    cc_payment_group_id: str | None
    is_duplicate: bool
    duplicate_group_id: str | None
    confidence: float
    flags_json: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
