"""Rules-first categorization engine."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class RuleEngine:
    def __init__(self, rules_dir: Path):
        self.rules_dir = rules_dir
        self.config = self._load_yaml("config.yaml")
        self.merchant_rules = self._load_yaml("merchant_rules.yaml").get("rules", [])

    def _load_yaml(self, name: str) -> dict[str, Any]:
        path = self.rules_dir / name
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def apply(self, description_norm: str, merchant_clean: str) -> tuple[str, str, str, str, float]:
        for rule in self.merchant_rules:
            if re.search(rule["pattern"], description_norm, flags=re.IGNORECASE):
                return (
                    rule.get("merchant_clean", merchant_clean),
                    rule.get("merchant_group", rule.get("merchant_clean", merchant_clean)),
                    rule.get("category", "Uncategorized"),
                    "RULE",
                    0.95,
                )

        up = description_norm.upper()
        transfer_kw = self.config.get("keywords", {}).get("transfer", ["TRANSFER", "IMPS", "NEFT", "UPI TO SELF"])
        cc_kw = self.config.get("keywords", {}).get("cc_payment", ["CREDIT CARD", "CARD PAYMENT", "CC PAYMENT", "CARD BILL"])

        if any(k in up for k in cc_kw):
            return merchant_clean, "Card Payments", "CC Payment", "HEURISTIC", 0.9
        if any(k in up for k in transfer_kw):
            return merchant_clean, "Transfers", "Transfers", "HEURISTIC", 0.85
        if any(k in up for k in ["GST", "CGST", "SGST", "MARKUP FEE"]):
            return merchant_clean, "Taxes", "Fees/Taxes", "HEURISTIC", 0.85
        if "OPENAI" in up or "CHATGPT" in up:
            return "OPENAI", "SaaS", "Subscriptions", "HEURISTIC", 0.9
        return merchant_clean, merchant_clean, "Uncategorized", "HEURISTIC", 0.5
