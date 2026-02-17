"""Shared utility helpers."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_spaces(text: str) -> str:
    return " ".join(text.split())


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)
