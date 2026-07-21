"""Assert-based self-check for extract.py's pure helpers + the SSRF guard + RRF fusion
in search.py. DB-free, no real network (the SSRF asserts only hit rejected local targets).
Run: python test_extract.py  OR  python -m pytest test_extract.py
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")  # capture.py/search.py import auth.py, which requires this at import time
os.environ.setdefault("DATABASE_URL", "postgresql://unused/unused")  # never connected in tests

from extract import extract_amounts, extract_dates, extract_emails, extract_phones, fetch_url
from search import fuse


def test_extract_emails():
    assert extract_emails("contact x a@b.com y") == ["a@b.com"]
    assert extract_emails("no email here") == []


def test_extract_phones():
    assert extract_phones("call 012-345 6789 now") != []


def test_extract_amounts():
    assert extract_amounts("that's RM50 please") == ["RM50"]
    assert extract_amounts("costs $5.00 total") == ["$5.00"]


def test_extract_dates():
    dates = extract_dates("let's meet on 3 January 2026")
    assert any("2026" in d for d in dates)
    assert extract_dates("zxcvbn qwerty asdfgh lorem ipsum") == []


def test_fetch_url_rejects_ssrf_targets():
    # loopback IP — must be rejected after DNS resolution, no request made
    assert fetch_url("http://127.0.0.1:80/") is None
    # non-http(s) scheme — must be rejected before any resolution
    assert fetch_url("file:///etc/passwd") is None


def test_rrf_fusion_prefers_ids_ranked_high_in_both():
    vector_ids = ["a", "b", "c"]
    fts_ids = ["b", "a", "d"]
    scores = fuse(vector_ids, fts_ids)
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    # "a" and "b" each appear near the top of both lists, "c"/"d" only appear in one
    assert ranked[0] in ("a", "b")
    assert ranked[1] in ("a", "b")
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["d"]


if __name__ == "__main__":
    test_extract_emails()
    test_extract_phones()
    test_extract_amounts()
    test_extract_dates()
    test_fetch_url_rejects_ssrf_targets()
    test_rrf_fusion_prefers_ids_ranked_high_in_both()
    print("all asserts passed")
