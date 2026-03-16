"""
test_bot.py v3 — Demo Zero Touch SimpleContext + Gemini

Cara pakai:
1. Isi TELEGRAM_TOKEN dan GEMINI_API_KEY
2. python test_bot.py
3. Chat di Telegram — bot otomatis route ke agent yang tepat

Commands:
  /start         — mulai
  /status        — lihat agent aktif + memori
  /agent <nama>  — paksa pakai agent tertentu
  /agent auto    — kembali ke auto-route
  /clear         — hapus history
  /agents        — daftar semua agent
"""

import logging, sys, os

# ── Isi ini ───────────────────────────────────────────────
TELEGRAM_TOKEN = "ISI_TOKEN_BOT_KAMU"
GEMINI_API_KEY = "ISI_GEMINI_API_KEY_KAMU"
GEMINI_MODEL   = "gemini/gemini-2.0-flash"
# ─────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Cek dependencies ──────────────────────────────────────
for pkg, install in [("telegram", "python-telegram-bot"), ("litellm", "litellm")]:
    try:
        __import__(pkg)
    except ImportError:
        print(f"❌ Install dulu: pip install {install}")
        sys.exit(1)

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import litellm
from simplecontext import SimpleContext

# ── Init SimpleContext ────────────────────────────────────
sc = SimpleContext(
    storage__backend = "sqlite",
    storage__path    = "./test_bot.db",
    agents__folder   = os.path.join(os.path.dirname(__file__), "agents"),
    agents__hot_reload = True,   # edit YAML → langsung aktif tanpa restart
    plugins__enabled = False,
)
log.info(f"✅ Agents loaded: {sc._registry.names()}")


# ── Helper ────────────────────────────────────────────────

def call_gemini(messages: list) -> str:
    try:
        resp = litellm.completion(
            model=GEMINI_MODEL, api_key=GEMINI_API_KEY,
            messages=messages, max_tokens=1024,
        )
        return resp.choices[0].message.content
    except Exception as e:
        log.error(f"Gemini error: {e}")
        return f"❌ Error: `{e}`"


# ── Handlers ──────────────────────────────────────────────

async def cmd_start(update: Update, ctx):
    user = update.effective_user
    mem  = sc.memory(user.id)
    mem.remember("nama", user.first_name)
    if user.username:
        mem.remember("username", f"@{user.username}")

    agents = sc._registry.names()
    await update.message.reply_text(
        f"👋 Halo *{user.first_name}*!\n\n"
        f"Nama kamu tersimpan di memori saya.\n\n"
        f"🤖 *Agent tersedia:* {', '.join(f'`{a}`' for a in agents)}\n\n"
        f"Bot akan otomatis pilih agent yang tepat.\n"
        f"Atau ketik /agent \\<nama\\> untuk pilih manual.",
        parse_mode="Markdown"
    )


async def cmd_agents(update: Update, ctx):
    agents = sc._registry.all()
    if not agents:
        await update.message.reply_text("Belum ada agent yang terdaftar.")
        return
    lines = ["🤖 *Daftar Agent:*\n"]
    for a in agents:
        kws = ", ".join(a.keywords[:4]) + ("..." if len(a.keywords) > 4 else "")
        lines.append(f"• *{a.name}* — {a.description}\n  Keywords: `{kws}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_agent(update: Update, ctx):
    uid  = update.effective_user.id
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Gunakan: /agent \\<nama\\> atau /agent auto\n"
            "Contoh: `/agent coding`",
            parse_mode="Markdown"
        )
        return
    name = args[0].lower()
    if name == "auto":
        sc.router.clear_user_agent(uid)
        await update.message.reply_text("✅ Kembali ke *auto-route*.", parse_mode="Markdown")
    else:
        try:
            sc.router.set_user_agent(uid, name)
            await update.message.reply_text(f"✅ Agent diset ke *{name}*.", parse_mode="Markdown")
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")


async def cmd_clear(update: Update, ctx):
    sc.memory(update.effective_user.id).clear()
    await update.message.reply_text("🗑 History dihapus! Profil tetap tersimpan.")


async def cmd_status(update: Update, ctx):
    uid  = update.effective_user.id
    mem  = sc.memory(uid)
    prof = mem.get_profile()
    result = sc.router.route(uid, "")
    prof_text = "\n".join(f"  • {k}: {v}" for k, v in prof.items()) or "  (kosong)"
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"🤖 Agent aktif: `{result.agent_id}`\n"
        f"💬 Pesan tersimpan: `{mem.count()}`\n\n"
        f"👤 *Profil:*\n{prof_text}",
        parse_mode="Markdown"
    )


async def handle_msg(update: Update, ctx):
    uid  = update.effective_user.id
    user = update.effective_user
    text = update.message.text

    # Auto-simpan nama
    mem = sc.memory(uid)
    if not mem.recall("nama"):
        mem.remember("nama", user.first_name)
        if user.username:
            mem.remember("username", f"@{user.username}")

    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")

    # ── Route ──────────────────────────────────────────────
    result   = sc.router.route(uid, text)
    messages = sc.prepare_messages(uid, text, result)

    log.info(f"[{user.username}] → agent={result.agent_id} level={result.personality_level}")

    # ── Call LLM ───────────────────────────────────────────
    reply = call_gemini(messages)

    # ── Chain: cek dari PESAN USER, bukan response LLM ────
    chain_rule = result.should_chain(text)   # FIX: pakai text (pesan user)
    if chain_rule:
        log.info(f"Chain: {result.agent_id} → {chain_rule['to']}")
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        result2   = sc.router.chain(uid, text, reply, chain_rule,
                                    from_agent_id=result.agent_id)  # FIX: track from_agent
        messages2 = sc.prepare_messages(uid, text, result2)
        reply     = call_gemini(messages2)
        # FIX: simpan metadata chain
        reply     = sc.process_response(uid, text, reply, result2,
                                        chain_from=result.agent_id)
    else:
        reply = sc.process_response(uid, text, reply, result)

    # ── Kirim ke Telegram ──────────────────────────────────
    try:
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(reply)


# ── Main ──────────────────────────────────────────────────

def main():
    if "ISI_" in TELEGRAM_TOKEN or "ISI_" in GEMINI_API_KEY:
        print("❌ Isi TELEGRAM_TOKEN dan GEMINI_API_KEY dulu!")
        sys.exit(1)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("agents", cmd_agents))
    app.add_handler(CommandHandler("agent",  cmd_agent))
    app.add_handler(CommandHandler("clear",  cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    log.info("🚀 Bot v3 berjalan... (Ctrl+C untuk stop)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
