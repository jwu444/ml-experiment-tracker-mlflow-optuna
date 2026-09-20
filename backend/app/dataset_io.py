from __future__ import annotations

import hashlib
import io

import pandas as pd


def decode_csv(raw: bytes) -> str:
    return raw.decode("utf-8")


def load_csv(data_csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(data_csv))


def hash_csv(raw: bytes) -> str:
    """SHA-256 of the raw upload bytes, as 64-char lowercase hex."""
    return hashlib.sha256(raw).hexdigest()
