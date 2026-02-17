"""Statement parser interfaces and built-in parser implementations."""
from __future__ import annotations

import csv
import io
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from finance_core.models import ParsedStatement
from finance_core.utils.common import normalize_spaces

logger = logging.getLogger(__name__)


class Parser(ABC):
    @abstractmethod
    def can_parse(self, path: Path, sniff_text_lines: list[str]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, path: Path) -> ParsedStatement:
        raise NotImplementedError


class ParserRegistry:
    """Order-sensitive parser registry."""

    def __init__(self, parsers: list[Parser] | None = None):
        self.parsers: list[Parser] = parsers or []

    def register(self, parser: Parser) -> None:
        self.parsers.append(parser)

    def parse(self, path: Path) -> ParsedStatement:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:30]
        for parser in self.parsers:
            if parser.can_parse(path, lines):
                logger.info("Using parser %s for %s", parser.__class__.__name__, path.name)
                return parser.parse(path)
        raise ValueError(f"No parser found for: {path}")


class DelimitedCardStatementParser(Parser):
    """Parses FORMAT A credit card statements with '~|~' delimiter."""

    DELIM = "~|~"
    HEADER_MARKER = "Domestic / International Transactions"
    EXPECTED = [
        "Transaction type",
        "Primary / Addon Customer Name",
        "DATE",
        "Description",
        "AMT",
        "Debit /Credit",
        "REWARDS",
    ]

    def can_parse(self, path: Path, sniff_text_lines: list[str]) -> bool:
        text = "\n".join(sniff_text_lines)
        return self.DELIM in text and self.HEADER_MARKER.lower() in text.lower()

    def parse(self, path: Path) -> ParsedStatement:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = [l.strip("\ufeff") for l in text.splitlines()]
        metadata: dict[str, Any] = {}
        start_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == self.HEADER_MARKER:
                start_idx = idx
                break
            if self.DELIM in line:
                parts = [p.strip() for p in line.split(self.DELIM)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    metadata[parts[0]] = parts[1]
        if start_idx is None:
            raise ValueError("Transaction section not found")

        header_idx = start_idx + 1
        while header_idx < len(lines) and not lines[header_idx].strip():
            header_idx += 1
        header = [h.strip() for h in lines[header_idx].split(self.DELIM)]
        if header[: len(self.EXPECTED)] != self.EXPECTED:
            raise ValueError(f"Unexpected header for card statement: {header}")

        rows: list[dict[str, Any]] = []
        for ridx, line in enumerate(lines[header_idx + 1 :], start=1):
            if not line.strip() or self.DELIM not in line:
                continue
            parts = [p.strip() for p in line.split(self.DELIM)]
            if len(parts) < len(self.EXPECTED):
                continue
            parsed = self._parse_row(parts, ridx)
            rows.append(parsed)

        return ParsedStatement(
            metadata=metadata,
            rows=rows,
            source_type_guess="credit",
            instrument_type="credit",
            account_hint=metadata.get("Card Number"),
        )

    def _parse_date(self, value: str) -> datetime:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        raise ValueError(f"Bad date: {value}")

    def _parse_row(self, parts: list[str], row_id: int) -> dict[str, Any]:
        dc = parts[5].upper()
        desc = parts[3]
        desc_upper = desc.upper()
        direction = "outflow"
        if "CREDIT" in dc or "REFUND" in desc_upper or "REVERSAL" in desc_upper:
            direction = "inflow"
        amount = float(parts[4])
        ref_match = re.search(r"Ref#\s*([A-Za-z0-9]+)", desc, flags=re.IGNORECASE)
        flags: list[str] = []
        if " USD" in desc_upper:
            flags.append("HAS_FX_TEXT")
        return {
            "row_id": row_id,
            "txn_date": self._parse_date(parts[2]),
            "posted_date": None,
            "description_raw": desc,
            "amount": amount,
            "currency": "INR",
            "direction": direction,
            "raw_ref": ref_match.group(1) if ref_match else None,
            "raw_balance": None,
            "flags": flags,
            "raw_json": {
                "transaction_type": parts[0],
                "customer_name": parts[1],
                "debit_credit": parts[5],
                "rewards": parts[6],
            },
        }


class BankTxtStatementParser(Parser):
    """Parses FORMAT B debit statement files (.txt/.csv comma separated)."""

    REQUIRED_COLUMNS = {
        "Date",
        "Narration",
        "Debit Amount",
        "Credit Amount",
        "Chq/Ref Number",
        "Closing Balance",
    }

    def can_parse(self, path: Path, sniff_text_lines: list[str]) -> bool:
        if path.suffix.lower() not in {".txt", ".csv"}:
            return False
        if not sniff_text_lines:
            return False
        header = sniff_text_lines[0]
        return all(col in header for col in ("Date", "Narration", "Debit Amount"))

    def parse(self, path: Path) -> ParsedStatement:
        text = path.read_text(encoding="utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
        rows = []
        for ridx, row in enumerate(reader, start=1):
            cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if not any(cleaned.values()):
                continue
            rows.append(self._parse_row(cleaned, ridx))
        return ParsedStatement(
            metadata={},
            rows=rows,
            source_type_guess="debit",
            instrument_type="debit",
            account_hint=None,
        )

    @staticmethod
    def _parse_date(value: str) -> datetime:
        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        raise ValueError(f"Bad date: {value}")

    def _parse_row(self, row: dict[str, str], row_id: int) -> dict[str, Any]:
        debit = float(row.get("Debit Amount", "0") or 0)
        credit = float(row.get("Credit Amount", "0") or 0)
        if debit > 0:
            direction, amount = "outflow", debit
        else:
            direction, amount = "inflow", credit
        return {
            "row_id": row_id,
            "txn_date": self._parse_date(row.get("Date", "")),
            "posted_date": self._parse_date(row.get("Value Dat", row.get("Date", ""))),
            "description_raw": normalize_spaces(row.get("Narration", "")),
            "amount": amount,
            "currency": "INR",
            "direction": direction,
            "raw_ref": row.get("Chq/Ref Number") or None,
            "raw_balance": float(row.get("Closing Balance", "0") or 0),
            "flags": [],
            "raw_json": row,
        }
