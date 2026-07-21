"""Assert-based self-check for capture.py's pure helpers — DB-free.
Run: python test_capture.py  OR  python -m pytest test_capture.py
"""
import os

os.environ.setdefault("DATA_DIR", "/tmp/engram-test-data")
os.environ.setdefault("JWT_SECRET", "test-secret")  # capture.py imports auth.py, which requires this at import time

from capture import CAPTURES_DIR, canonical_hash, infer_kind, safe_ext


def test_canonical_hash_stable_and_distinct():
    assert canonical_hash(b"hi") == canonical_hash(b"hi")
    assert canonical_hash(b"hi") != canonical_hash(b"ho")


def test_infer_kind():
    assert infer_kind("https://x.co/a", None, None) == "url"
    assert infer_kind("note", None, None) == "text"
    assert infer_kind(None, "p.jpg", "image/jpeg") == "photo"
    assert infer_kind(None, "v.ogg", "audio/ogg") == "audio"
    assert infer_kind(None, "report.pdf", "application/pdf") == "file"


def test_safe_ext_blocks_path_traversal():
    ext = safe_ext("../../etc/passwd")
    assert "/" not in ext and "\\" not in ext and ".." not in ext
    # resulting storage path must stay inside CAPTURES_DIR
    stored = os.path.normpath(f"{CAPTURES_DIR}/somename{ext}")
    assert stored.startswith(os.path.normpath(CAPTURES_DIR))


def test_safe_ext_keeps_normal_extension():
    assert safe_ext("photo.JPG") == ".JPG"


if __name__ == "__main__":
    test_canonical_hash_stable_and_distinct()
    test_infer_kind()
    test_safe_ext_blocks_path_traversal()
    test_safe_ext_keeps_normal_extension()
    print("all asserts passed")
