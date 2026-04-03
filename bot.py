import os, json, logging
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ─── КОНФИГ ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_KEY", "")

ADMINS_FILE  = "admins.json"
HISTORY_FILE = "histories.json"
NOTES_FILE   = "notes.json"

DEFAULT_SYSTEM = (
    "Ты — Клод, умный помощник и DevOps-ассистент Анатолия. "
    "Отвечай на русском языке. Ты работаешь в Telegram-боте. "
    "Помогаешь с проектами: ФЕРМА, Общее Дело, Помощник судьи, LZT Autopilot. "
    "Когда пользователь просит что-то сделать на сервере — предлагай конкретные команды."
)

SUPER_ADMINS = {270589758, 108863518}

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── КЛИЕНТ ───────────────────────────────────────────────────────────────────
client = OpenAI(
    api_key=ANTHROPIC_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# ─── ХРАНИЛИЩЕ ────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, ensure_ascii=False, indent=2)

admins   = set(load_json(ADMINS_FILE, [])) | SUPER_ADMINS
histories = load_json(HISTORY_FILE, {})
notes    = load_json(NOTES_FILE, {})  # {user_id: [{title, summary, date}]}

def save_admins(): save_json(ADMINS_FILE, list(admins))
def save_histories(): save_json(HISTORY_FILE, histories)
def save_notes(): save_json(NOTES_FILE, notes)

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def is_admin(uid): return uid in admins or uid in SUPER_ADMINS
def is_super(uid): return uid in SUPER_ADMINS

def get_history(uid):
    return histories.get(str(uid), [])

def set_history(uid, h):
    histories[str(uid)] = h[-40:]
    save_histories()

def get_system(uid):
    for m in get_history(uid):
        if m.get("_type") == "system": return m["content"]
    return DEFAULT_SYSTEM

def get_dialog(uid):
    return [m for m in get_history(uid) if m.get("_type") != "system"]

def get_notes(uid):
    return notes.get(str(uid), [])

def add_note(uid, title, summary):
    from datetime import datetime
    user_notes = get_notes(uid)
    user_notes.insert(0, {
        "title": title,
        "summary": summary,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    })
    notes[str(uid)] = user_notes[:30]  # макс 30 заметок
    save_notes()

# ─── АВТО-РЕЗЮМЕ ──────────────────────────────────────────────────────────────
async def auto_summarize(uid, dialog):
    """Создаёт краткое резюме диалога после 6+ сообщений"""
    if len(dialog) < 6:
        return
    # Берём последние 6 сообщений для резюме
    recent = dialog[-6:]
    text = "\n".join([f"{'Пользователь' if m['role']=='user' else 'Клод'}: {m['content'][:200]}" for m in recent])
    try:
        resp = client.chat.completions.create(
            model="anthropic/claude-sonnet-4-5",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"Дай краткое резюме этого диалога в 2-3 предложения. Первая строка — короткий заголовок (до 50 символов). Формат:\nЗаголовок: ...\nРезюме: ...\n\nДиалог:\n{text}"
            }]
        )
        result = resp.choices[0].message.content
        title = "Диалог"
        summary = result
        for line in result.split("\n"):
            if line.startswith("Заголовок:"):
                title = line.replace("Заголовок:", "").strip()
            elif line.startswith("Резюме:"):
                summary = line.replace("Резюме:", "").strip()
        add_note(uid, title, summary)
        log.info(f"Auto-summary saved for user {uid}: {title}")
    except Exception as e:
        log.error(f"Summary error: {e}")

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def main_keyboard(uid):
    buttons = [
        [
            InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
            InlineKeyboardButton("📓 Заметки", callback_data="notes"),
        ],
        [
            InlineKeyboardButton("📜 История", callback_data="history"),
            InlineKeyboardButton("🗑 Очистить", callback_data="clear"),
        ],
        [
            InlineKeyboardButton("⚙️ Промпт", callback_data="show_system"),
            InlineKeyboardButton("📋 Мой ID", callback_data="myid"),
        ],
        [
            InlineKeyboardButton("🌐 Claude.ai", url="https://claude.ai"),
            InlineKeyboardButton("📚 Диалоги", url="http://195.123.228.234:8080/history.html"),
        ],
    ]
    if is_admin(uid):
        buttons.append([
            InlineKeyboardButton("👥 Админы", callback_data="admins"),
            InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt"),
        ])
    return InlineKeyboardMarkup(buttons)

def back_keyboard(to="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=to)]])

def servers_keyboard():
    buttons = [
        [InlineKeyboardButton("🌾 ФЕРМА (195.123.228.234)", callback_data="srv_ferma")],
        [InlineKeyboardButton("🤝 Общее Дело (85.90.197.57)", callback_data="srv_obshchee")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(buttons)

def server_keyboard(key):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статус", callback_data=f"srv_{key}_status"),
            InlineKeyboardButton("📋 Логи", callback_data=f"srv_{key}_logs"),
        ],
        [
            InlineKeyboardButton("🔄 Рестарт", callback_data=f"srv_{key}_restart"),
            InlineKeyboardButton("💾 Диск", callback_data=f"srv_{key}_disk"),
        ],
        [InlineKeyboardButton("⌨️ Своя команда", callback_data=f"srv_{key}_custom")],
        [InlineKeyboardButton("◀️ Серверы", callback_data="servers")],
    ])

# ─── SSH ──────────────────────────────────────────────────────────────────────
SERVERS = {
    "ferma": {
        "label": "🌾 ФЕРМА",
        "host": "195.123.228.234",
        "user": "root",
        "password": os.environ.get("FERMA_PASS", ""),
        "services": ["claude-bot", "claude-web"],
    },
    "obshchee": {
        "label": "🤝 Общее Дело",
        "host": "85.90.197.57",
        "user": "root",
        "password": os.environ.get("OBSHCHEE_PASS", ""),
        "services": ["obshchee-delo"],
    },
}

def ssh_exec(key, command, timeout=30):
    import paramiko
    srv = SERVERS.get(key)
    if not srv: return "❌ Сервер не найден"
    if not srv["password"]: return "❌ Пароль не задан"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(srv["host"], port=22, username=srv["user"], password=srv["password"], timeout=10)
        _, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        ssh.close()
        result = out or err or "✅ Выполнено"
        return result[:3500]
    except Exception as e:
        return f"❌ SSH: {e}"

# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(f"⛔ Доступ закрыт. Твой ID: `{uid}`", parse_mode="Markdown")
        return
    name = update.effective_user.first_name or "незнакомец"
    role = "👑 суперадмин" if is_super(uid) else "🔑 администратор"
    msg_count = len([m for m in get_dialog(uid) if m["role"] == "user"])
    notes_count = len(get_notes(uid))
    await update.message.reply_text(
        f"Привет, *{name}*! Ты — {role}\n\n"
        f"💬 Сообщений: *{msg_count}*\n"
        f"📓 Заметок: *{notes_count}*\n"
        f"🖥 Серверов: *{len(SERVERS)}*\n\n"
        "Пиши — я отвечу и помогу управлять проектами:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(uid)
    )

# ─── CALLBACK ─────────────────────────────────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if not is_admin(uid):
        await q.answer("⛔ Нет доступа", show_alert=True)
        return

    if data == "menu":
        name = q.from_user.first_name or "незнакомец"
        role = "👑 суперадмин" if is_super(uid) else "🔑 администратор"
        msg_count = len([m for m in get_dialog(uid) if m["role"] == "user"])
        notes_count = len(get_notes(uid))
        await q.edit_message_text(
            f"Привет, *{name}*! Ты — {role}\n\n"
            f"💬 Сообщений: *{msg_count}*\n"
            f"📓 Заметок: *{notes_count}*\n"
            f"🖥 Серверов: *{len(SERVERS)}*\n\n"
            "Пиши — я отвечу и помогу управлять проектами:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(uid)
        )

    # ── Заметки ──
    elif data == "notes":
        user_notes = get_notes(uid)
        if not user_notes:
            await q.edit_message_text(
                "📓 *Заметок пока нет*\n\n"
                "Они создаются автоматически после каждого диалога из 6+ сообщений.\n"
                "Или напиши мне: _«сохрани заметку: ...»_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Очистить все", callback_data="notes_clear")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
                ])
            )
            return
        lines = ["📓 *Мои заметки:*\n"]
        for i, n in enumerate(user_notes[:10], 1):
            lines.append(f"*{i}. {n['title']}*")
            lines.append(f"_{n['summary']}_")
            lines.append(f"🕐 {n['date']}\n")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Очистить все", callback_data="notes_clear")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "notes_clear":
        notes[str(uid)] = []
        save_notes()
        await q.edit_message_text("✅ Заметки очищены", reply_markup=back_keyboard())

    # ── Серверы ──
    elif data == "servers":
        await q.edit_message_text("🖥 *Выбери сервер:*", parse_mode="Markdown", reply_markup=servers_keyboard())

    elif data.startswith("srv_") and data.count("_") == 1:
        key = data[4:]
        srv = SERVERS.get(key, {})
        await q.edit_message_text(
            f"{srv.get('label','?')}\n`{srv.get('host','')}`",
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    elif data.endswith("_status"):
        key = data[4:-7]
        srv = SERVERS.get(key, {})
        await q.edit_message_text(f"⏳ Проверяю {srv.get('label','?')}...")
        lines = [f"📊 *{srv.get('label','?')}*\n"]
        for svc in srv.get("services", []):
            out = ssh_exec(key, f"systemctl is-active {svc}")
            icon = "🟢" if "active" in out else "🔴"
            lines.append(f"{icon} `{svc}`")
        uptime = ssh_exec(key, "uptime -p")
        mem = ssh_exec(key, "free -h | awk 'NR==2{print $3\"/\"$2}'")
        lines += [f"\n⏱ {uptime}", f"💾 RAM: {mem}"]
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_logs"):
        key = data[4:-5]
        srv = SERVERS.get(key, {})
        await q.edit_message_text(f"⏳ Получаю логи...")
        svc = srv.get("services", [""])[0]
        logs = ssh_exec(key, f"journalctl -u {svc} -n 15 --no-pager -o short 2>/dev/null")
        await q.edit_message_text(f"```\n{logs}\n```", parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_restart"):
        key = data[4:-8]
        srv = SERVERS.get(key, {})
        if not is_super(uid):
            await q.answer("⛔ Только суперадмины", show_alert=True)
            return
        await q.edit_message_text(f"🔄 Перезапускаю...")
        results = []
        for svc in srv.get("services", []):
            out = ssh_exec(key, f"systemctl restart {svc} && echo OK")
            results.append(f"{'✅' if 'OK' in out else '❌'} `{svc}`")
        await q.edit_message_text("\n".join(results), parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_disk"):
        key = data[4:-5]
        srv = SERVERS.get(key, {})
        await q.edit_message_text("⏳ Проверяю диск...")
        disk = ssh_exec(key, "df -h / | tail -1")
        await q.edit_message_text(f"💾 *Диск:*\n```\n{disk}\n```", parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_custom"):
        key = data[4:-7]
        srv = SERVERS.get(key, {})
        ctx.user_data["waiting_for"] = f"ssh_{key}"
        await q.edit_message_text(
            f"⌨️ Введи команду для *{srv.get('label','?')}*:",
            parse_mode="Markdown",
            reply_markup=back_keyboard(f"srv_{key}")
        )

    # ── История ──
    elif data == "history":
        dialog = get_dialog(uid)
        if not dialog:
            await q.edit_message_text("📭 История пуста!", reply_markup=back_keyboard())
            return
        pairs, i = [], 0
        while i < len(dialog):
            if dialog[i]["role"] == "user":
                u = dialog[i]["content"][:80] + ("…" if len(dialog[i]["content"]) > 80 else "")
                b = ""
                if i+1 < len(dialog) and dialog[i+1]["role"] == "assistant":
                    b = dialog[i+1]["content"][:100] + ("…" if len(dialog[i+1]["content"]) > 100 else "")
                    i += 2
                else: i += 1
                pairs.append((u, b))
        last = pairs[-5:]
        lines = [f"📜 *Последние {len(last)} сообщений:*\n"]
        for n, (u, b) in enumerate(last, 1):
            lines.append(f"*{n}.* {u}")
            if b: lines.append(f"🤖 {b}\n")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Очистить", callback_data="clear")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "clear":
        h = [m for m in get_history(uid) if m.get("_type") == "system"]
        set_history(uid, h)
        await q.edit_message_text("✅ История очищена!", reply_markup=back_keyboard())

    elif data == "myid":
        await q.edit_message_text(f"📋 Твой ID:\n\n`{uid}`", parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "show_system":
        system = get_system(uid)
        await q.edit_message_text(
            f"⚙️ *Системный промпт:*\n\n_{system}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить", callback_data="system_prompt")],
                [InlineKeyboardButton("🔄 Сброс", callback_data="system_reset")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "system_prompt":
        ctx.user_data["waiting_for"] = "system_prompt"
        await q.edit_message_text("✏️ Введи новый системный промпт:", reply_markup=back_keyboard())

    elif data == "system_reset":
        h = [m for m in get_history(uid) if m.get("_type") != "system"]
        set_history(uid, h)
        await q.edit_message_text("✅ Промпт сброшен", reply_markup=back_keyboard())

    elif data == "admins":
        lines = ["👑 *Суперадмины:*"] + [f"  `{i}`" for i in sorted(SUPER_ADMINS)]
        regular = admins - SUPER_ADMINS
        if regular: lines += ["\n🔑 *Администраторы:*"] + [f"  `{i}`" for i in sorted(regular)]
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "addadmin_prompt":
        ctx.user_data["waiting_for"] = "addadmin"
        await q.edit_message_text("➕ Введи Telegram ID:", reply_markup=back_keyboard())

# ─── СООБЩЕНИЯ ────────────────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(f"⛔ Доступ закрыт. ID: `{uid}`", parse_mode="Markdown")
        return

    text = update.message.text
    waiting = ctx.user_data.get("waiting_for")

    if waiting and waiting.startswith("ssh_"):
        ctx.user_data.pop("waiting_for")
        key = waiting[4:]
        srv = SERVERS.get(key, {})
        await update.message.reply_text(f"⏳ Выполняю на *{srv.get('label','?')}*:\n`{text}`", parse_mode="Markdown")
        result = ssh_exec(key, text)
        await update.message.reply_text(f"```\n{result}\n```", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🖥 Сервер", callback_data=f"srv_{key}"),
                InlineKeyboardButton("☰ Меню", callback_data="menu"),
            ]])
        )
        return

    if waiting == "system_prompt":
        ctx.user_data.pop("waiting_for")
        h = [m for m in get_history(uid) if m.get("_type") != "system"]
        h.insert(0, {"_type": "system", "content": text})
        set_history(uid, h)
        await update.message.reply_text(f"✅ Промпт обновлён:\n_{text}_", parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return

    if waiting == "addadmin":
        ctx.user_data.pop("waiting_for")
        try:
            new_id = int(text.strip())
            admins.add(new_id)
            save_admins()
            await update.message.reply_text(f"✅ `{new_id}` добавлен!", parse_mode="Markdown", reply_markup=main_keyboard(uid))
        except:
            await update.message.reply_text("❌ Неверный ID", reply_markup=main_keyboard(uid))
        return

    # ── Сохранить заметку вручную ──
    if text.lower().startswith("сохрани заметку:") or text.lower().startswith("запомни:"):
        content = text.split(":", 1)[1].strip()
        add_note(uid, "📝 Заметка", content)
        await update.message.reply_text("✅ Заметка сохранена!", reply_markup=main_keyboard(uid))
        return

    # ── Диалог с Claude ──
    h = get_history(uid)
    system_prompt = DEFAULT_SYSTEM
    messages = []
    for m in h:
        if m.get("_type") == "system": system_prompt = m["content"]
        else: messages.append(m)

    messages.append({"role": "user", "content": text})
    await update.message.chat.send_action("typing")

    try:
        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4-5",
            max_tokens=2000,
            messages=[{"role": "system", "content": system_prompt}] + messages
        )
        reply = response.choices[0].message.content
    except Exception as e:
        log.error(f"API error: {e}")
        await update.message.reply_text(f"❌ Ошибка: `{e}`", parse_mode="Markdown")
        return

    messages.append({"role": "assistant", "content": reply})
    system_entries = [m for m in h if m.get("_type") == "system"]
    set_history(uid, system_entries + messages)

    # Авто-резюме каждые 6 сообщений
    dialog = [m for m in system_entries + messages if m.get("_type") != "system"]
    if len(dialog) % 6 == 0 and len(dialog) > 0:
        await auto_summarize(uid, dialog)

    reply_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
        InlineKeyboardButton("📓 Заметки", callback_data="notes"),
        InlineKeyboardButton("☰ Меню", callback_data="menu"),
    ]])

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            is_last = i + 4000 >= len(reply)
            await update.message.reply_text(reply[i:i+4000], reply_markup=reply_kb if is_last else None)
    else:
        await update.message.reply_text(reply, reply_markup=reply_kb)

    log.info(f"OK | user={uid} | in={len(text)}ch | out={len(reply)}ch")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN: print("❌ TELEGRAM_TOKEN не задан"); return
    if not ANTHROPIC_KEY:  print("❌ ANTHROPIC_KEY не задан"); return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Bot started with Notes + SSH")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
