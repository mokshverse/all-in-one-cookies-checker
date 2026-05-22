"""
Prime Video Cookie Checker — storefront + HTML parse
Based on: github.com/harshitkamboj/PrimeVideo-Cookie-Checker
"""
import re
import requests
from .base import parse_cookies, make_result, new_session, rex
from config import TIMEOUT

CHECK_URLS = [
    "https://www.primevideo.com/storefront/home",
    "https://www.primevideo.com/",
    "https://www.amazon.com/gp/video/storefront",
]

PRIME_H = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

SESSION_KEYS = [
    "session-token", "ubid-main", "at-main",
    "sess-at-main", "x-main", "lc-main",
    "session-id", "ubid-acbuk", "ubid-acbus",
    "ubid-acbde", "ubid-acbfr", "ubid-acbjp",
]

SIGNIN_MARKERS = ["signin", "ap/signin", "auth/signin", "ap/register", "sign-in"]


def _parse(html: str) -> dict:
    src = html.replace('\\"', '"').replace("&quot;", '"')
    combined = html + "\n" + src
    name = rex(combined,
        r'"customerName"\s*:\s*"([^"]{2,60})"',
        r'class="[^"]*nav-line-1[^"]*"[^>]*>([^<]{2,40})<',
        r'"displayName"\s*:\s*"([^"]{2,60})"',
    )
    return {
        "name":     "" if (not name or "sign" in name.lower()) else name,
        "country":  (rex(combined, r'"countryCode"\s*:\s*"([A-Z]{2})"',
                                   r'"marketplaceCountry"\s*:\s*"([^"]{2,5})"',
                                   r'"locale"\s*:\s*"[a-z]{2}-([A-Z]{2})"') or "").upper(),
        "profile":  rex(combined, r'"activeProfile"[^}]*?"name"\s*:\s*"([^"]{1,50})"',
                                  r'"profileName"\s*:\s*"([^"]{1,50})"'),
        "is_prime": any(k in combined for k in ['"isPrime":true', '"hasPrimeMembership":true',
                                                 '"isAmazonPrime":true', '"PRIME"']),
        "is_free":  '"isPrime":false' in combined or '"hasPrimeMembership":false' in combined,
        "next_billing": rex(combined, r'"nextBillingDate"\s*:\s*"([^"]+)"',
                                      r'"renewalDate"\s*:\s*"([^"]+)"'),
    }


def check(content: str, filename: str) -> dict:
    cookies = parse_cookies(content)
    if not any(cookies.get(k) for k in SESSION_KEYS):
        return make_result(filename, content, "INVALID",
                           "Missing session-token / at-main cookie")

    s = new_session(cookies, PRIME_H)
    try:
        resp = None
        last_code = None
        for url in CHECK_URLS:
            try:
                r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
                last_code = r.status_code
                final_url = r.url.lower()
                if any(m in final_url for m in SIGNIN_MARKERS):
                    continue
                if r.status_code == 403:
                    return make_result(filename, content, "BANNED", "403 — Account restricted")
                if r.status_code == 200:
                    if 'id="ap_email"' in r.text and "ap_password" in r.text:
                        continue
                    resp = r
                    break
            except Exception:
                continue

        if resp is None:
            return make_result(filename, content, "INVALID",
                               "Redirected to sign-in — cookie expired")

        info = _parse(resp.text)
        extra = {}
        if info["name"]:          extra["name"]         = info["name"]
        if info["country"]:       extra["country"]      = info["country"]
        if info["profile"]:       extra["profile"]      = info["profile"]
        if info["next_billing"]:  extra["next_billing"] = info["next_billing"]
        extra["plan"] = (
            "Prime (Paid)" if info["is_prime"]
            else "Free / No Prime" if info["is_free"]
            else "Unknown"
        )
        return make_result(filename, content, "VALID", "Cookie working ✓", extra)

    except requests.exceptions.Timeout:
        return make_result(filename, content, "TIMEOUT", "Request timed out")
    except Exception as e:
        return make_result(filename, content, "ERROR", str(e))
