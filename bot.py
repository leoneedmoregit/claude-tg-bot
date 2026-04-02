import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)
import anthropic

# ─── КОНФИГ ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_KEY", "")

ADMINS_FILE  = "admins.json"
HISTORY_FILE = "histories.json"

DEFAULT_SYSTEM = "Ты умный помощник. Отвечай на русском языке."
SUPER_ADMINS   = {270589758, 108863518}

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── ХРАНИЛИЩЕ ────────────────────────────────────────────────────────────────
def load_admins() -> set:
    try:
        with open(ADMINS_FILE) as f: return set(json.load(f))
    except: return set()

def save_admins(admins: set):
    with open(ADMINS_FILE, "w") as f: json.dump(list(admins), f)

def load_histories() -> dict:
    try:
        with open(HISTORY_FILE) as f: return json.load(f)
    except: return {}

def save_histories(h: dict):
    with open(HISTORY_FILE, "w") as f: json.dump(h, f, ensure_ascii=False)

admins    = load_admins() | SUPER_ADMINS
histories = load_histories()
client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def is_admin(uid): return uid in admins or uid in SUPER_ADMINS
def is_super(uid): return uid in SUPER_ADMINS
def uid(update): return update.effective_user.id

def get_history(user_id):
    return histories.get(str(user_id), [])

def set_history(user_id, h):
    histories[str(user_id)] = h[-40:]
    save_histories(histories)

def get_system(user_id):
    for m in get_history(user_id):
        if m.get("_type") == "system":
            return m["content"]
    return DEFAULT_SYSTEM

def get_dialog(user_id):
    return [m for m in get_history(user_id) if m.get("_type") != "system"]

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def main_keyboard(user_id):
    buttons = [
        [
            InlineKeyboardButton("💬 Последние сообщения", callback_data="history"),
            InlineKeyboardButton("🗑 Очистить", callback_data="clear"),
        ],
        [
            InlineKeyboardButton("⚙️ Системный промпт", callback_data="show_system"),
            InlineKeyboardButton("📋 Мой ID", callback_data="myid"),
        ],
        [
            InlineKeyboardButton("🌐 Claude.ai", url="https://claude.ai"),
            InlineKeyboardButton("📁 Anthropic Console", url="https://console.anthropic.com"),
        ],
    ]
    if is_admin(user_id):
        buttons.append([
            InlineKeyboardButton("👥 Список админов", callback_data="admins"),
            InlineKeyboardButton("➕ Добавить админа", callback_data="addadmin_prompt"),
        ])
    return InlineKeyboardMarkup(buttons)

def back_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="menu")
    ]])

def system_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data="system_prompt")],
        [InlineKeyboardButton("🔄 Сбросить к дефолту", callback_data="system_reset")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
    ])

# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = uid(update)
    name = update.effective_user.first_name or "незнакомец"
    role = "👑 суперадмин" if is_super(user_id) else "🔑 администратор" if is_admin(user_id) else None

    if not role:
        await update.message.reply_text(
            f"⛔ Доступ закрыт.\n\nТвой ID: `{user_id}`\n"
            "Попроси администратора добавить тебя командой `/addadmin`",
            parse_mode="Markdown"
        )
        return

    dialog = get_dialog(user_id)
    msg_count = len([m for m in dialog if m["role"] == "user"])

    await update.message.reply_text(
        f"Привет, *{name}*! Ты — {role}\n\n"
        f"📊 Сообщений в истории: *{msg_count}*\n"
        f"🤖 Модель: claude-opus-4-5\n\n"
        "Просто пиши мне — я отвечу. Или используй меню:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ─── CALLBACK КНОПКИ ──────────────────────────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = q.data

    if data == "menu":
        name = q.from_user.first_name or "незнакомец"
        role = "👑 суперадмин" if is_super(user_id) else "🔑 администратор" if is_admin(user_id) else "👤"
        dialog = get_dialog(user_id)
        msg_count = len([m for m in dialog if m["role"] == "user"])
        await q.edit_message_text(
            f"Привет, *{name}*! Ты — {role}\n\n"
            f"📊 Сообщений в истории: *{msg_count}*\n"
            f"🤖 Модель: claude-opus-4-5\n\n"
            "Просто пиши мне — я отвечу. Или используй меню:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(user_id)
        )

    elif data == "history":
        dialog = get_dialog(user_id)
        if not dialog:
            await q.edit_message_text(
                "📭 История пуста — начни диалог!",
                reply_markup=back_keyboard()
            )
            return

        # Последние 5 пар
        pairs = []
        i = 0
        while i < len(dialog):
            if dialog[i]["role"] == "user":
                user_msg = dialog[i]["content"][:80] + ("…" if len(dialog[i]["content"]) > 80 else "")
                bot_msg = ""
                if i + 1 < len(dialog) and dialog[i+1]["role"] == "assistant":
                    bot_msg = dialog[i+1]["content"][:120] + ("…" if len(dialog[i+1]["content"]) > 120 else "")
                    i += 2
                else:
                    i += 1
                pairs.append((user_msg, bot_msg))
        
        last = pairs[-5:]
        lines = [f"📜 *Последние {len(last)} сообщений:*\n"]
        for n, (u, b) in enumerate(last, 1):
            lines.append(f"*{n}. Ты:* {u}")
            if b:
                lines.append(f"*🤖:* {b}\n")

        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Очистить историю", callback_data="clear")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "clear":
        h = get_history(user_id)
        system_entries = [m for m in h if m.get("_type") == "system"]
        set_history(user_id, system_entries)
        await q.edit_message_text(
            "✅ *История диалога очищена!*\n\nМожешь начинать новый разговор.",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif data == "myid":
        await q.edit_message_text(
            f"📋 *Твой Telegram ID:*\n\n`{user_id}`\n\n"
            "Скопируй и передай администратору для получения доступа.",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif data == "show_system":
        system = get_system(user_id)
        is_default = system == DEFAULT_SYSTEM
        await q.edit_message_text(
            f"⚙️ *Системный промпт:*\n\n_{system}_\n\n"
            f"{'📌 Дефолтный' if is_default else '✏️ Кастомный'}",
            parse_mode="Markdown",
            reply_markup=system_keyboard() if is_admin(user_id) else back_keyboard()
        )

    elif data == "system_reset":
        if not is_admin(user_id):
            await q.answer("⛔ Недостаточно прав", show_alert=True)
            return
        h = [m for m in get_history(user_id) if m.get("_type") != "system"]
        set_history(user_id, h)
        await q.edit_message_text(
            "✅ *Системный промпт сброшен* к дефолтному:\n\n_" + DEFAULT_SYSTEM + "_",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif data == "system_prompt":
        if not is_admin(user_id):
            await q.answer("⛔ Недостаточно прав", show_alert=True)
            return
        ctx.user_data["waiting_for"] = "system_prompt"
        await q.edit_message_text(
            "✏️ *Введи новый системный промпт:*\n\n"
            "Например: _Ты краткий и точный помощник. Отвечай только по делу._\n\n"
            "Просто напиши текст в чат:",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif data == "admins":
        if not is_admin(user_id):
            await q.answer("⛔ Недостаточно прав", show_alert=True)
            return
        lines = ["👑 *Суперадмины:*"] + [f"  `{i}`" for i in sorted(SUPER_ADMINS)]
        regular = admins - SUPER_ADMINS
        if regular:
            lines += ["\n🔑 *Администраторы:*"] + [f"  `{i}`" for i in sorted(regular)]
        else:
            lines.append("\n_Дополнительных нет_")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "addadmin_prompt":
        if not is_admin(user_id):
            await q.answer("⛔ Недостаточно прав", show_alert=True)
            return
        ctx.user_data["waiting_for"] = "addadmin"
        await q.edit_message_text(
            "➕ *Добавить администратора*\n\n"
            "Введи Telegram ID пользователя в чат:\n"
            "_(попроси его написать /myid боту)_",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

# ─── ОБРАБОТЧИК СООБЩЕНИЙ ─────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = uid(update)

    if not is_admin(user_id):
        await update.message.reply_text(
            f"⛔ Доступ закрыт.\n\nТвой ID: `{user_id}`\n"
            "Попроси администратора добавить тебя через `/addadmin`",
            parse_mode="Markdown"
        )
        log.warning(f"Unauthorized: {user_id}")
        return

    text = update.message.text
    waiting = ctx.user_data.get("waiting_for")

    # ── Ожидаем системный промпт ──
    if waiting == "system_prompt":
        ctx.user_data.pop("waiting_for")
        h = [m for m in get_history(user_id) if m.get("_type") != "system"]
        h.insert(0, {"_type": "system", "content": text})
        set_history(user_id, h)
        await update.message.reply_text(
            f"✅ *Системный промпт обновлён:*\n\n_{text}_",
            parse_mode="Markdown",
            reply_markup=main_keyboard(user_id)
        )
        return

    # ── Ожидаем ID для addadmin ──
    if waiting == "addadmin":
        ctx.user_data.pop("waiting_for")
        try:
            new_id = int(text.strip())
            admins.add(new_id)
            save_admins(admins)
            log.info(f"Admin {user_id} added {new_id}")
            await update.message.reply_text(
                f"✅ Пользователь `{new_id}` получил права администратора!",
                parse_mode="Markdown",
                reply_markup=main_keyboard(user_id)
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный ID — должно быть число. Попробуй ещё раз.",
                reply_markup=main_keyboard(user_id)
            )
        return

    # ── Обычный диалог с Claude ──
    h = get_history(user_id)
    system_prompt = DEFAULT_SYSTEM
    messages = []
    for m in h:
        if m.get("_type") == "system":
            system_prompt = m["content"]
        else:
            messages.append(m)

    messages.append({"role": "user", "content": text})
    await update.message.chat.send_action("typing")

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            system=system_prompt,
            messages=messages
        )
        reply = response.content[0].text
    except Exception as e:
        log.error(f"API error user={user_id}: {e}")
        await update.message.reply_text(f"❌ Ошибка API:\n`{e}`", parse_mode="Markdown")
        return

    messages.append({"role": "assistant", "content": reply})
    system_entries = [m for m in h if m.get("_type") == "system"]
    set_history(user_id, system_entries + messages)

    # Кнопки под каждым ответом
    reply_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📜 История", callback_data="history"),
        InlineKeyboardButton("🗑 Очистить", callback_data="clear"),
        InlineKeyboardButton("☰ Меню", callback_data="menu"),
    ]])

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            chunk = reply[i:i+4000]
            is_last = (i + 4000 >= len(reply))
            await update.message.reply_text(
                chunk,
                reply_markup=reply_kb if is_last else None
            )
    else:
        await update.message.reply_text(reply, reply_markup=reply_kb)

    log.info(f"OK | user={user_id} | in={len(text)}ch | out={len(reply)}ch")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN: print("❌ TELEGRAM_TOKEN не задан"); return
    if not ANTHROPIC_KEY:  print("❌ ANTHROPIC_KEY не задан"); return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("menu",   cmd_menu))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Bot started with UI")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
