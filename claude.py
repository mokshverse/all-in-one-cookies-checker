"""
Claude AI Cookie Checker — /api/organizations + /api/account
"""
import requests
from .base import parse_cookies, make_result, new_session
from config import TIMEOUT

ORG_URL     = "https://claude.ai/api/organizations"
ACCOUNT_URL = "https://claude.ai/api/account"

CLAUDE_H = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://claude.ai/",
    "Origin": "https://claude.ai",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def check(content: str, filename: str) -> dict:
    cookies = parse_cookies(content)
    session_key = cookies.get("sessionKey", "")
    if not session_key or not session_key.startswith("sk-ant-"):
        return make_result(filename, content, "INVALID",
                           "Missing sessionKey (must start with sk-ant-)")

    s = new_session(cookies, CLAUDE_H)
    try:
        r = s.get(ORG_URL, timeout=TIMEOUT)
        if r.status_code == 401:
            return make_result(filename, content, "INVALID", "Cookie expired (401)")
        if r.status_code == 403:
            return make_result(filename, content, "BANNED",  "Account suspended (403)")
        if r.status_code == 429:
            return make_result(filename, content, "RATE_LIMITED", "Rate limited")
        if r.status_code != 200:
            return make_result(filename, content, "UNKNOWN", f"HTTP {r.status_code}")

        extra = {"session_key_preview": session_key[:28] + "..."}
        try:
            orgs = r.json()
            if isinstance(orgs, list) and orgs:
                org = orgs[0]
                extra["org"]  = org.get("name", "")
                tier  = org.get("billing_subscription_tier", "")
                flags = org.get("active_flags", [])
                extra["plan"] = (
                    tier.replace("_", " ").title() if tier
                    else "Pro" if any("pro" in str(f).lower() for f in flags)
                    else "Free"
                )
                rl = org.get("rate_limit_tier", "")
                if rl: extra["rate_limit_tier"] = rl
        except Exception:
            pass

        try:
            ra = s.get(ACCOUNT_URL, timeout=TIMEOUT)
            if ra.status_code == 200:
                acc = ra.json()
                extra["email"] = acc.get("email_address", "")
                extra["name"]  = acc.get("full_name") or acc.get("display_name") or ""
        except Exception:
            pass

        return make_result(filename, content, "VALID", "Cookie working ✓", extra)

    except requests.exceptions.Timeout:
        return make_result(filename, content, "TIMEOUT", "Timed out")
    except Exception as e:
        return make_result(filename, content, "ERROR", str(e))
