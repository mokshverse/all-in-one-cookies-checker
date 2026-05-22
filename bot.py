import os
import io
import zipfile
import threading
import time
from queue import Queue

import telebot
from telebot.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import BOT_TOKEN, MAX_THREADS
from checkers import PLATFORMS

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
print(f"[BOT] Starting — threads={MAX_THREADS}")

selected_platform: dict[int, str] = {}

# ─── Platform meta ────────────────────────────────────────────────────────────

PLATFORM_ICONS = {
    "claude":     "🤖",
    "netflix":    "🎬",
    "spotify":    "🎵",
    "primevideo": "📺",
    "chatgpt":    "💬",
}

def platform_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(*[
        InlineKeyboardButton(
            f"{PLATFORM_ICONS[k]}  {v['name']}",
            callback_data=f"platform:{k}",
        )
        for k, v in PLATFORMS.items()
    ])
    return kb

# ─── Result formatting ────────────────────────────────────────────────────────

STATUS_INFO = {
    "VALID":        ("✅", "WORKING"),
    "FREE":         ("🆓", "FREE"),
    "INVALID":      ("❌", "INVALID"),
    "BANNED":       ("⛔", "BANNED"),
    "RATE_LIMITED": ("⚠️", "RATE LIMITED"),
    "TIMEOUT":      ("⏱", "TIMEOUT"),
    "ERROR":        ("🔴", "ERROR"),
    "UNKNOWN":      ("❓", "UNKNOWN"),
}

EXTRA_LABELS = [
    ("email",               "📧 Email"),
    ("name",                "👤 Name"),
    ("org",                 "🏢 Org"),
    ("plan",                "💎 Plan"),
    ("country",             "🌍 Country"),
    ("membership",          "🎫 Status"),
    ("role",                "👑 Role"),
    ("profile",             "🎭 Profile"),
    ("profiles",            "🎭 Profiles"),
    ("max_streams",         "📺 Screens"),
    ("quality",             "🖥 Quality"),
    ("next_billing",        "📅 Next Bill"),
    ("member_since",        "📆 Member Since"),
    ("payment",             "💳 Payment"),
    ("extra_members",       "👥 Extra Members"),
    ("free_slots",          "🪑 Free Slots"),
    ("invite_url",          "🔗 Invite"),
    ("trial",               "🎁 Trial"),
    ("rate_limit_tier",     "⚡ Rate Tier"),
    ("session_key_preview", "🔑 Key"),
]


def format_result(r: dict) -> str:
    emoji, label = STATUS_INFO.get(r["status"], ("❓", r["status"]))
    lines = [f"{emoji} *{label}*  ›  `{r['file']}`"]
    for key, lbl in EXTRA_LABELS:
        val = r.get(key, "")
        if val:
            lines.append(f"   {lbl}: {val}")
    if r["status"] not in ("VALID", "FREE"):
        lines.append(f"   ℹ️ {r['message']}")
    return "\n".join(lines)


def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def safe_send(chat_id, text):
    try:
        bot.send_message(chat_id, text[:4096], parse_mode="Markdown")
    except Exception:
        try:
            bot.send_message(chat_id, text[:4096], parse_mode=None)
        except Exception:
            pass


def safe_edit(chat_id, msg_id, text):
    try:
        bot.edit_message_text(text[:4096], chat_id, msg_id, parse_mode="Markdown")
    except Exception:
        pass

# ─── Progress bar helper ──────────────────────────────────────────────────────

def _bar(pct: int, width=12) -> str:
    filled = int(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def _progress_text(icon, name, total, done, valid, invalid, banned, errors, threads):
    pct       = int(done / total * 100) if total else 0
    remaining = total - done
    return (
        f"{icon} *{name}*\n"
        f"┌─────────────────────────\n"
        f"│ `[{_bar(pct)}]` *{pct}%*\n"
        f"├─────────────────────────\n"
        f"│ 🔢 Total      `{total}`\n"
        f"│ ⏳ Done       `{done}` / `{total}`\n"
        f"│ 🔄 Remaining  `{remaining}`\n"
        f"├─────────────────────────\n"
        f"│ ✅ Valid      `{valid}`\n"
        f"│ ❌ Invalid    `{invalid}`\n"
        f"│ ⛔ Banned     `{banned}`\n"
        f"│ 🔴 Errors     `{errors}`\n"
        f"└─────────────────────────\n"
        f"⚡ *{threads}* threads · checking..."
    )


def _summary_text(icon, name, total, valid, invalid, banned, rate, errors):
    hit_pct = int(valid / total * 100) if total else 0
    return (
        f"{icon} *{name} — Done!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Results*\n"
        f"  🔢 Total       `{total}`\n"
        f"  ✅ Working     `{valid}`  ({hit_pct}%)\n"
        f"  ❌ Invalid     `{invalid}`\n"
        f"  ⛔ Banned      `{banned}`\n"
        f"  ⚠️  Rate Ltd    `{rate}`\n"
        f"  🔴 Errors      `{errors}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

# ─── Threading ────────────────────────────────────────────────────────────────

def worker(q: Queue, results: list, lock: threading.Lock, check_fn):
    while True:
        item = q.get()
        if item is None:
            q.task_done()
            break
        fname, content = item
        result = check_fn(content, fname)
        with lock:
            results.append(result)
        q.task_done()


def run_checks(cookie_files, check_fn, chat_id, msg_id, icon, name):
    total    = len(cookie_files)
    results  = []
    lock     = threading.Lock()
    q        = Queue()
    all_done = threading.Event()

    for fname, content in cookie_files.items():
        q.put((fname, content))

    thread_count = min(MAX_THREADS, total)
    threads = []
    for _ in range(thread_count):
        t = threading.Thread(
            target=worker, args=(q, results, lock, check_fn), daemon=True
        )
        t.start()
        threads.append(t)

    def _waiter():
        q.join()
        all_done.set()

    threading.Thread(target=_waiter, daemon=True).start()

    last_done = -1
    while not all_done.is_set():
        with lock:
            done = len(results)
            snap = list(results)

        if done != last_done:
            last_done = done
            v = sum(1 for r in snap if r["status"] in ("VALID", "FREE"))
            i = sum(1 for r in snap if r["status"] == "INVALID")
            b = sum(1 for r in snap if r["status"] == "BANNED")
            e = sum(1 for r in snap if r["status"] in ("ERROR","TIMEOUT","UNKNOWN","RATE_LIMITED"))
            safe_edit(chat_id, msg_id,
                      _progress_text(icon, name, total, done, v, i, b, e, thread_count))

        all_done.wait(timeout=1.2)

    # Final 100% update
    with lock:
        snap = list(results)
    v = sum(1 for r in snap if r["status"] in ("VALID", "FREE"))
    i = sum(1 for r in snap if r["status"] == "INVALID")
    b = sum(1 for r in snap if r["status"] == "BANNED")
    e = sum(1 for r in snap if r["status"] in ("ERROR","TIMEOUT","UNKNOWN","RATE_LIMITED"))
    safe_edit(chat_id, msg_id,
              _progress_text(icon, name, total, total, v, i, b, e, thread_count))

    for _ in threads:
        q.put(None)
    for t in threads:
        t.join(timeout=5)

    return results

# ─── Result zip ──────────────────────────────────────────────────────────────

def build_zip(valid: list) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in valid:
            zf.writestr(r["file"], r["raw_content"])
    buf.seek(0)
    return buf

# ─── Handlers ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def handle_start(message: Message):
    bot.send_message(
        message.chat.id,
        "👋 *Cookie Checker Bot*\n\n"
        "_Multi-platform checker: Netflix, Spotify, Prime, ChatGPT, Claude_\n\n"
        "🔽 *Select a platform to begin:*",
        reply_markup=platform_keyboard(),
    )


@bot.message_handler(commands=["check"])
def handle_check(message: Message):
    bot.send_message(
        message.chat.id,
        "🔽 *Select platform:*",
        reply_markup=platform_keyboard(),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("platform:"))
def handle_platform(call: CallbackQuery):
    uid = call.from_user.id
    key = call.data.split(":", 1)[1]
    if key not in PLATFORMS:
        bot.answer_callback_query(call.id, "❌ Unknown platform")
        return

    p = PLATFORMS[key]
    icon = PLATFORM_ICONS[key]
    bot.answer_callback_query(call.id, f"{p['name']} selected ✅")
    selected_platform[uid] = key

    bot.edit_message_text(
        f"{icon} *{p['name']}* selected ✅\n\n"
        f"📦 Send a `.zip` file containing cookie `.txt` files\n"
        f"_Formats: Netscape (tab-separated) or JSON array_\n\n"
        f"↩️ Change platform: /check",
        call.message.chat.id,
        call.message.message_id,
    )


@bot.message_handler(content_types=["document"])
def handle_document(message: Message):
    uid = message.from_user.id
    doc = message.document

    if not doc.file_name.lower().endswith(".zip"):
        bot.reply_to(message, "❌ Please send a `.zip` file only.")
        return

    if uid not in selected_platform:
        bot.reply_to(
            message,
            "⚠️ Select a platform first:",
            reply_markup=platform_keyboard(),
        )
        return

    platform_key = selected_platform.pop(uid)
    platform     = PLATFORMS[platform_key]
    icon         = PLATFORM_ICONS[platform_key]

    status_msg = bot.reply_to(message, "⬇️ Downloading zip...")

    try:
        fi  = bot.get_file(doc.file_id)
        raw = bot.download_file(fi.file_path)
    except Exception as e:
        safe_edit(message.chat.id, status_msg.message_id, f"❌ Download failed: {e}")
        return

    try:
        zf    = zipfile.ZipFile(io.BytesIO(raw))
        names = zf.namelist()
    except zipfile.BadZipFile:
        safe_edit(message.chat.id, status_msg.message_id, "❌ Invalid zip file.")
        return

    cookie_names = [
        n for n in names
        if n.lower().endswith(".txt") and not n.startswith("__MACOSX")
    ]
    if not cookie_names:
        safe_edit(message.chat.id, status_msg.message_id,
                  "❌ No `.txt` cookie files found in zip.")
        return

    tc = min(MAX_THREADS, len(cookie_names))
    safe_edit(
        message.chat.id, status_msg.message_id,
        f"{icon} *{platform['name']}* — `{len(cookie_names)}` files found\n"
        f"⚡ Starting with `{tc}` threads...",
    )

    def do_check():
        try:
            cookie_files = {}
            for n in cookie_names:
                try:
                    content = zf.read(n).decode("utf-8", errors="ignore")
                    cookie_files[os.path.basename(n)] = content
                except Exception:
                    pass

            total   = len(cookie_files)
            results = run_checks(
                cookie_files, platform["fn"],
                message.chat.id, status_msg.message_id,
                icon, platform["name"],
            )

            valid   = [r for r in results if r["status"] in ("VALID", "FREE")]
            invalid = [r for r in results if r["status"] == "INVALID"]
            banned  = [r for r in results if r["status"] == "BANNED"]
            rate    = [r for r in results if r["status"] == "RATE_LIMITED"]
            errors  = [r for r in results if r["status"] in ("ERROR", "TIMEOUT", "UNKNOWN")]

            # Final summary card
            safe_edit(
                message.chat.id, status_msg.message_id,
                _summary_text(icon, platform["name"], total,
                               len(valid), len(invalid), len(banned), len(rate), len(errors)),
            )
            time.sleep(0.5)

            # ── Working cookies first ──────────────────────────────────────
            if valid:
                header = (
                    f"✅ *WORKING COOKIES ({len(valid)}/{total})*\n"
                    f"{'─' * 28}"
                )
                safe_send(message.chat.id, header)
                for batch in chunk_list(valid, 5):
                    safe_send(message.chat.id,
                              "\n\n".join(format_result(r) for r in batch))
                    time.sleep(0.3)

            # ── Invalid / Banned / Errors ─────────────────────────────────
            bad_all = invalid + banned + rate + errors
            if bad_all:
                header = (
                    f"❌ *INVALID / FAILED ({len(bad_all)}/{total})*\n"
                    f"{'─' * 28}"
                )
                safe_send(message.chat.id, header)
                for batch in chunk_list(bad_all, 8):
                    safe_send(message.chat.id,
                              "\n\n".join(format_result(r) for r in batch))
                    time.sleep(0.3)

            # ── Send working cookies zip ───────────────────────────────────
            if valid:
                zip_buf = build_zip(valid)

                lines = [f"📦 *{platform['name']} — Working Cookies* `{len(valid)}/{total}`\n"]
                for r in valid:
                    parts = [p for p in [
                        r.get("email"), r.get("plan"), r.get("country")
                    ] if p]
                    info = "  ·  ".join(parts)
                    lines.append(f"✅ `{r['file']}`" + (f"\n     {info}" if info else ""))

                lines.append(f"\n/check — check more cookies")
                caption = "\n".join(lines)[:1020]

                try:
                    bot.send_document(
                        message.chat.id,
                        (f"{platform_key}_working_cookies.zip", zip_buf),
                        caption=caption,
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    safe_send(message.chat.id, f"⚠️ Could not send zip: {e}")

            else:
                safe_send(
                    message.chat.id,
                    f"😔 *No working {platform['name']} cookies found.*\n\n"
                    f"Try different cookies · /check",
                )

        except Exception as e:
            safe_send(message.chat.id, f"🔴 *Fatal error:* `{e}`")

    threading.Thread(target=do_check, daemon=True).start()


# ─── Launch ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[BOT] Polling...")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
