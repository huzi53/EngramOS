"""Tier-1 heuristic extraction: plain regex/stdlib functions plus a SSRF-guarded URL
fetch + OCR. Every extractor fails soft (returns empty) — a capture must save even if
one extractor errors on hostile input.
"""
import ipaddress
import re
import socket
from io import BytesIO
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)\d{3,4}[-.\s]?\d{3,4}")
# RM first — Malaysian ringgit is the common case for this user.
AMOUNT_RE = re.compile(r"(?:RM|\$|€|£)\s?\d[\d,]*(?:\.\d+)?")

FETCH_TIMEOUT = 5.0
MAX_FETCH_BYTES = 512 * 1024
MAX_REDIRECTS = 3


def extract_emails(text: str) -> list[str]:
    return EMAIL_RE.findall(text or "")


def extract_phones(text: str) -> list[str]:
    return [m.strip() for m in PHONE_RE.findall(text or "")]


def extract_amounts(text: str) -> list[str]:
    return AMOUNT_RE.findall(text or "")


def extract_dates(text: str) -> list[str]:
    if not text:
        return []
    try:
        from dateparser.search import search_dates
        found = search_dates(text)
    except Exception:
        # dateparser can be slow/raise on junk input — dates are best-effort, never fatal.
        return []
    if not found:
        return []
    return [dt.isoformat() for _, dt in found]


def _is_safe_host(host: str) -> bool:
    """SSRF guard: resolve the host and reject anything private/loopback/link-local/reserved.
    Must run AFTER DNS resolution — checking the literal hostname alone lets a public
    DNS name that resolves to 127.0.0.1/169.254.x.x/etc. slip through.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def fetch_url(url: str) -> str | None:
    """SSRF-guarded GET: http(s) only, private/loopback/link-local/reserved IPs rejected
    after resolution, bounded timeout/redirects/size, HTML-ish content-type required.

    Redirects are followed manually (httpx's own follow_redirects=True would connect to
    each hop BEFORE we get a chance to check it) so every hop's host is validated by
    _is_safe_host() prior to connecting to it, not after the fact.
    Returns response text or None on any rejection/failure — never raises.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname or not _is_safe_host(parsed.hostname):
        return None
    try:
        with httpx.Client(follow_redirects=False, timeout=FETCH_TIMEOUT) as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", url) as r:
                    if r.has_redirect_location:
                        next_url = str(r.url.join(r.headers["location"]))
                        next_host = urlparse(next_url).hostname
                        # ponytail: host is validated here but not pinned to the IP the
                        # next request actually connects to, so a low-TTL DNS-rebinding
                        # attacker could still slip a hop past this check. Real fix needs
                        # a custom transport that connects to the checked IP directly;
                        # skipped since this needs precise attacker DNS timing and is a
                        # single-user authed app, not multi-tenant.
                        if not next_host or not _is_safe_host(next_host):
                            return None
                        url = next_url
                        continue
                    content_type = r.headers.get("content-type", "")
                    if "html" not in content_type and "text" not in content_type:
                        return None
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_FETCH_BYTES:
                            break
                    return body[:MAX_FETCH_BYTES].decode(r.encoding or "utf-8", errors="replace")
            return None  # exceeded MAX_REDIRECTS
    except Exception:
        return None


def extract_url_metadata(url: str) -> dict:
    html = fetch_url(url)
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return {}
    out = {}
    og_title = soup.find("meta", property="og:title")
    title = (og_title and og_title.get("content")) or (soup.title and soup.title.string)
    if title:
        out["url_title"] = title.strip()
    og_desc = soup.find("meta", property="og:description")
    desc = (og_desc and og_desc.get("content")) or (soup.find("meta", attrs={"name": "description"}) or {}).get("content")
    if desc:
        out["url_description"] = desc.strip()
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        out["url_image"] = og_image["content"].strip()
    return out


def ocr_image(file_bytes: bytes) -> str:
    """Best-effort OCR — returns "" on any failure (corrupt image, tesseract missing,
    decompression bomb). Never fatal to a capture.
    """
    try:
        from PIL import Image
        import pytesseract
        # Decompression-bomb guard: refuse to decode absurdly large images.
        Image.MAX_IMAGE_PIXELS = 40_000_000
        img = Image.open(BytesIO(file_bytes))
        return pytesseract.image_to_string(img, timeout=10).strip()
    except Exception:
        return ""
