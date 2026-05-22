"""
ChatGPT Cookie Checker — /api/auth/session + /backend-api/me
Key: split session tokens (.0, .1, .2 ...) must be concatenated
"""
import requests
from .base import parse_cookies, make_result, new_session
from config import TIMEOUT

SESSION_URL = "https://chatgpt.com/api/auth/session"
ME_URL      = "https://chatgpt.com/backend-api/me"
SUB_URL     = "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"

BASE_H = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://chatgpt.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def _concat_token(cookies: dict) -> str:
    for key in ("__Secure-next-auth.session-token", "next-auth.session-token"):
        v = cookies.get(key, "")
        if v:
            return v
    parts: dict[int, str] = {}
    for key, val in cookies.items():
        for prefix in ("__Secure-next-auth.session-token.", "next-auth.session-token."):
            if key.startswith(prefix):
                suffix = key[len(prefix):]
                if suffix.isdigit():
                    parts[int(suffix)] = val
                break
    return "".join(v for _, v in sorted(parts.items()))


def check(content: str, filename: str) -> dict:
    cookies = parse_cookies(content)
    token = _concat_token(cookies)
    if not token:
        return make_result(filename, content, "INVALID",
                           "__Secure-next-auth.session-token not found")

    s = new_session(cookies, BASE_H)
    try:
        r = s.get(SESSION_URL, timeout=TIMEOUT)
        if r.status_code == 401:
            return make_result(filename, content, "INVALID", "Cookie expired (401)")
        if r.status_code == 403:
            return make_result(filename, content, "BANNED",  "Account restricted (403)")
        if r.status_code == 429:
            return make_result(filename, content, "RATE_LIMITED", "Rate limited")
        if r.status_code != 200:
            return make_result(filename, content, "UNKNOWN", f"HTTP {r.status_code}")

        try:
            data = r.json()
        except Exception:
            return make_result(filename, content, "INVALID", "Bad response from ChatGPT")

        user = data.get("user")
        if not user:
            return make_result(filename, content, "INVALID", "No user — cookie expired")

        extra = {"email": user.get("email", ""), "name": user.get("name", "")}
        access_token = data.get("accessToken", "")

        if access_token:
            auth_h = {**BASE_H, "Authorization": f"Bearer {access_token}"}
            try:
                me = requests.get(ME_URL, headers=auth_h, timeout=TIMEOUT).json()
                extra["email"] = me.get("email") or extra["email"]
                extra["name"]  = me.get("name")  or extra["name"]
                orgs = me.get("orgs", {}).get("data", [])
                if orgs:
                    extra["org"] = orgs[0].get("title", "")
            except Exception:
                pass

            try:
                sub = requests.get(SUB_URL, headers=auth_h, timeout=TIMEOUT).json()
                for acc in sub.get("accounts", {}).values():
                    plan = acc.get("plan_type") or acc.get("entitlement", {}).get("subscription_plan", "")
                    feats = acc.get("features", [])
                    if any(f in feats for f in ("gpt4", "gpt4o", "gpt-4")):
                        extra["plan"] = "Plus / Pro"
                    elif plan:
                        extra["plan"] = plan.replace("_", " ").title()
                    break
            except Exception:
                pass

        if not extra.get("plan"):
            extra["plan"] = "Free"

        return make_result(filename, content, "VALID", "Cookie working ✓", extra)

    except requests.exceptions.Timeout:
        return make_result(filename, content, "TIMEOUT", "Timed out")
    except Exception as e:
        return make_result(filename, content, "ERROR", str(e))
