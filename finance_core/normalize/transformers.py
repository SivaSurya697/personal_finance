"""Normalization helpers and canonical fingerprinting."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from finance_core.utils.common import normalize_spaces

REF_RE = re.compile(r"\(?\s*Ref#\s*[A-Za-z0-9]+\)?", re.IGNORECASE)


def normalize_description(description_raw: str) -> str:
    text = description_raw.upper().strip()
    text = REF_RE.sub("", text)
    text = text.replace("UPI-", "UPI ")
    text = re.sub(r"-+", " ", text)
    return normalize_spaces(text)


def extract_merchant(description_norm: str) -> tuple[str, str]:
    if description_norm.startswith("UPI "):
        parts = description_norm.split()
        merchant = parts[1] if len(parts) > 1 else "UPI"
        return merchant, "UPI"
    first = description_norm.split("/")[0].split("-")[0].split()[0:3]
    merchant = " ".join(first) if first else "UNKNOWN"
    return merchant, merchant


def build_fingerprint(
    account_id: str,
    txn_date: datetime,
    amount: float,
    direction: str,
    description_norm: str,
    raw_ref: str | None,
) -> str:
    payload = "|".join(
        [
            account_id,
            txn_date.date().isoformat(),
            f"{amount:.2f}",
            direction,
            description_norm,
            raw_ref or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
