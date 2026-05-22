import json
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
        "Gecko/20100101 Firefox/132.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}

def _make_adapter():
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    return HTTPAdapter(
        max_retries=retry,
        pool_connections=20,
        pool_maxsize=50,
        pool_block=False,
    )


def parse_netscape(content: str) -> dict:
    cookies = {}
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5].strip()] = parts[6].strip()
    return cookies


def parse_json_cookies(content: str) -> dict:
    cookies = {}
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                name = item.get("name", "")
                value = item.get("value", "")
                if name:
                    cookies[name] = value
    except Exception:
        pass
    return cookies


def parse_raw(content: str) -> dict:
    cookies = {}
    for part in content.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def parse_cookies(content: str) -> dict:
    stripped = content.strip()
    if stripped.startswith("["):
        r = parse_json_cookies(stripped)
        if r:
            return r
    if "\t" in stripped:
        return parse_netscape(stripped)
    return parse_raw(stripped)


def make_result(file, raw, status, message, extra=None):
    r = {"file": file, "raw_content": raw, "status": status, "message": message}
    if extra:
        r.update(extra)
    return r


def new_session(cookies: dict, extra_headers: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    adapter = _make_adapter()
    s.mount("https://", adapter)
    s.mount("http://",  adapter)
    s.headers.update(HEADERS_BASE)
    if extra_headers:
        s.headers.update(extra_headers)
    s.cookies.update(cookies)
    return s


def rex(text: str, *patterns, flags=re.IGNORECASE) -> str:
    combined = text.replace('\\"', '"').replace("&quot;", '"')
    for pat in patterns:
        m = re.search(pat, combined, flags)
        if m:
            return m.group(1).strip()
    return ""
