import io

import pandas as pd
from app.dataset_io import decode_csv, hash_csv, load_csv
from pandas.testing import assert_frame_equal


def test_decode_returns_raw_text():
    raw = b"age,city\n20,NY\n30,LA\n"
    assert decode_csv(raw) == "age,city\n20,NY\n30,LA\n"


def test_round_trip_matches_pandas_parse():
    raw = b"age,city\n20,NY\n30,NY\n40,LA\n"
    restored = load_csv(decode_csv(raw))
    expected = pd.read_csv(io.BytesIO(raw))
    assert_frame_equal(restored, expected)


def test_hash_csv_is_deterministic_64_hex():
    raw = b"a,b\n1,2\n"
    digest = hash_csv(raw)
    assert digest == hash_csv(raw)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_csv_distinguishes_content():
    assert hash_csv(b"a,b\n1,2\n") != hash_csv(b"a,b\n1,3\n")
