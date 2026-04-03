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

ADMINS_FILE   = "admins.json"
HISTORY_FILE  = "histories.json"
NOTES_FILE    = "notes.json"
PROJECTS_FILE = "projects.json"

DEFAULT_SYSTEM = (
    "Ты — Клод, умный помощник и DevOps-ассистент Анатолия. "
    "Отвечай на русском языке. Ты работаешь в Telegram-боте. "
    "Помогаешь с проектами: ФЕРМА, Общее Дело, Помощник судьи, LZT Autopilot. "
    "Когда пользователь просит что-то сделать на сервере — предлагай конкретные команды."
)

SUPER_ADMINS = {270589758, 108863518}

# ─── ПРОЕКТЫ ──────────────────────────────────────────────────────────────────
PROJECTS = {
    "ferma": {
        "emoji": "🌾",
        "name": "ФЕРМА",
        "desc": "Android-ферма, инвайтер, TeleRaptor",
        "system": "Ты помогаешь с проектом ФЕРМА — Android-ферма на ADB, массовые инвайты через TeleRaptor, aiogram-бот, Google Sheets РОЗАЛИНД. Сервер: 195.123.228.234.",
        "color": "🟢"
    },
    "obshchee": {
        "emoji": "🤝",
        "name": "Общее Дело",
        "desc": "Краудинвест платформа, FastAPI + React",
        "system": "Ты помогаешь с проектом Общее Дело — краудинвестиционная платформа. FastAPI + SQLite + React + Nginx. Сервер: 85.90.197.57. GitHub: leoneedmoregit/obshchee-delo.",
        "color": "🔵"
    },
    "sudya": {
        "emoji": "⚖️",
        "name": "Помощник судьи",
        "desc": "AI-сервис для судей, помощник-судьи.рф",
        "system": "Ты помогаешь с проектом Помощник судьи — AI-сервис на помощник-судьи.рф. ~264 пользователя, 85 активных. Email-рассылка по судам, промокод НЕТЗАВАЛАМ.",
        "color": "🟡"
    },
    "lzt": {
        "emoji": "⚡",
        "name": "LZT Autopilot",
        "desc": "Автозакупка Telegram-аккаунтов",
        "system": "Ты помогаешь с проектом LZT Autopilot — автозакупка Telegram-аккаунтов с LZT Market, отправка на share-access.ru. Веб-дашборд порт 5050. RDP-сервер 89.31.112.106.",
        "color": "🔴"
    },
    "claude_bot": {
        "emoji": "🤖",
        "name": "Claude Бот",
        "desc": "Этот Telegram-бот с Claude внутри",
        "system": "Ты помогаешь с разработкой этого Telegram-бота. GitHub: leoneedmoregit/claude-tg-bot. Сервер: 195.123.228.234. OpenRouter API.",
        "color": "🟣"
    },
    "ielts": {
        "emoji": "🎓",
        "name": "IELTS Buddy",
        "desc": "Бот подготовки к IELTS Speaking",
        "system": "Ты помогаешь с проектом IELTS Buddy — Telegram-бот для подготовки к IELTS Speaking. Groq API (Whisper + llama), edge-tts. Хостинг на Replit.",
        "color": "🔵"
    },
}

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

client = OpenAI(api_key=ANTHROPIC_KEY, base_url="https://openrouter.ai/api/v1")

# ─── ХРАНИЛИЩЕ ────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, ensure_ascii=False, indent=2)

admins    = set(load_json(ADMINS_FILE, [])) | SUPER_ADMINS
histories = load_json(HISTORY_FILE, {})
notes     = load_json(NOTES_FILE, {})
proj_hist = load_json(PROJECTS_FILE, {})  # {uid: {project_key: [messages]}}

def save_admins():    save_json(ADMINS_FILE, list(admins))
def save_histories(): save_json(HISTORY_FILE, histories)
def save_notes():     save_json(NOTES_FILE, notes)
def save_proj_hist(): save_json(PROJECTS_FILE, proj_hist)

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
    user_notes.insert(0, {"title": title, "summary": summary, "date": datetime.now().strftime("%d.%m %H:%M")})
    notes[str(uid)] = user_notes[:30]
    save_notes()

# Проектная история
def get_proj_history(uid, proj_key):
    return proj_hist.get(str(uid), {}).get(proj_key, [])

def set_proj_history(uid, proj_key, h):
    if str(uid) not in proj_hist: proj_hist[str(uid)] = {}
    proj_hist[str(uid)][proj_key] = h[-30:]
    save_proj_hist()

# ─── SSH ──────────────────────────────────────────────────────────────────────
SERVERS = {
    "ferma":   {"label": "🌾 ФЕРМА",       "host": "195.123.228.234", "user": "root", "password": os.environ.get("FERMA_PASS",""),   "services": ["claude-bot","claude-web"]},
    "obshchee":{"label": "🤝 Общее Дело",  "host": "85.90.197.57",   "user": "root", "password": os.environ.get("OBSHCHEE_PASS",""),"services": ["obshchee-delo"]},
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
        return (out or err or "✅ Выполнено")[:3500]
    except Exception as e:
        return f"❌ SSH: {e}"

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Проекты", callback_data="projects"),
            InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
        ],
        [
            InlineKeyboardButton("📓 Заметки", callback_data="notes"),
            InlineKeyboardButton("📜 История", callback_data="history"),
        ],
        [
            InlineKeyboardButton("⚙️ Промпт", callback_data="show_system"),
            InlineKeyboardButton("🗑 Очистить", callback_data="clear"),
        ],
        [
            InlineKeyboardButton("🌐 Claude.ai", url="https://claude.ai"),
            InlineKeyboardButton("📚 Диалоги", url="http://195.123.228.234:8080/history.html"),
        ],
        *([[InlineKeyboardButton("👥 Админы", callback_data="admins"),
            InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt")]] if is_admin(uid) else [])
    ])

def projects_keyboard():
    buttons = []
    row = []
    for key, p in PROJECTS.items():
        row.append(InlineKeyboardButton(f"{p['emoji']} {p['name']}", callback_data=f"proj_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)

def project_keyboard(key):
    p = PROJECTS[key]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💬 Открыть диалог", callback_data=f"proj_{key}_chat")],
        [InlineKeyboardButton(f"📜 История проекта", callback_data=f"proj_{key}_history")],
        [InlineKeyboardButton(f"🗑 Очистить историю", callback_data=f"proj_{key}_clear")],
        [InlineKeyboardButton("◀️ Проекты", callback_data="projects")],
    ])

def back_keyboard(to="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=to)]])

def servers_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌾 ФЕРМА (195.123.228.234)", callback_data="srv_ferma")],
        [InlineKeyboardButton("🤝 Общее Дело (85.90.197.57)", callback_data="srv_obshchee")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
    ])

def server_keyboard(key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data=f"srv_{key}_status"),
         InlineKeyboardButton("📋 Логи", callback_data=f"srv_{key}_logs")],
        [InlineKeyboardButton("🔄 Рестарт", callback_data=f"srv_{key}_restart"),
         InlineKeyboardButton("💾 Диск", callback_data=f"srv_{key}_disk")],
        [InlineKeyboardButton("⌨️ Своя команда", callback_data=f"srv_{key}_custom")],
        [InlineKeyboardButton("◀️ Серверы", callback_data="servers")],
    ])

def chat_keyboard(proj_key=None):
    if proj_key:
        p = PROJECTS[proj_key]
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📁 {p['name']}", callback_data=f"proj_{proj_key}"),
            InlineKeyboardButton("📜 История", callback_data=f"proj_{proj_key}_history"),
            InlineKeyboardButton("☰ Меню", callback_data="menu"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
        InlineKeyboardButton("📓 Заметки", callback_data="notes"),
        InlineKeyboardButton("☰ Меню", callback_data="menu"),
    ]])

# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(f"⛔ Доступ закрыт. ID: `{uid}`", parse_mode="Markdown")
        return
    # Сброс режима проекта
    ctx.user_data.pop("project", None)
    name = update.effective_user.first_name or "незнакомец"
    role = "👑 суперадмин" if is_super(uid) else "🔑 администратор"
    await update.message.reply_text(
        f"Привет, *{name}*! Ты — {role}\n\n"
        f"💬 Сообщений: *{len([m for m in get_dialog(uid) if m['role']=='user'])}*\n"
        f"📓 Заметок: *{len(get_notes(uid))}*\n"
        f"📁 Проектов: *{len(PROJECTS)}*\n\n"
        "Пиши мне — я отвечу. Или выбери проект:",
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

    # ── Главное меню ──
    if data == "menu":
        ctx.user_data.pop("project", None)
        name = q.from_user.first_name or "незнакомец"
        role = "👑 суперадмин" if is_super(uid) else "🔑 администратор"
        await q.edit_message_text(
            f"Привет, *{name}*! Ты — {role}\n\n"
            f"💬 Сообщений: *{len([m for m in get_dialog(uid) if m['role']=='user'])}*\n"
            f"📓 Заметок: *{len(get_notes(uid))}*\n"
            f"📁 Проектов: *{len(PROJECTS)}*\n\n"
            "Пиши мне — я отвечу. Или выбери проект:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(uid)
        )

    # ── Проекты ──
    elif data == "projects":
        ctx.user_data.pop("project", None)
        lines = ["📁 *Выбери проект:*\n"]
        for key, p in PROJECTS.items():
            h = get_proj_history(uid, key)
            msg_count = len([m for m in h if m.get("role") == "user"])
            lines.append(f"{p['emoji']} *{p['name']}* — {p['desc']} _{f'({msg_count} сообщ.)' if msg_count else '(нет истории)'}_")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=projects_keyboard())

    elif data.startswith("proj_") and data.count("_") == 1:
        key = data[5:]
        if key not in PROJECTS: return
        p = PROJECTS[key]
        h = get_proj_history(uid, key)
        msg_count = len([m for m in h if m.get("role") == "user"])
        await q.edit_message_text(
            f"{p['emoji']} *{p['name']}*\n\n"
            f"_{p['desc']}_\n\n"
            f"💬 Сообщений в истории: *{msg_count}*\n\n"
            f"Нажми *«Открыть диалог»* — и все следующие сообщения будут сохраняться в историю этого проекта.",
            parse_mode="Markdown",
            reply_markup=project_keyboard(key)
        )

    elif data.startswith("proj_") and data.endswith("_chat"):
        key = data[5:-5]
        if key not in PROJECTS: return
        p = PROJECTS[key]
        ctx.user_data["project"] = key
        await q.edit_message_text(
            f"{p['emoji']} *Диалог: {p['name']}*\n\n"
            f"Режим проекта активен. Все твои сообщения будут сохраняться в историю *{p['name']}*.\n\n"
            f"Пиши свой вопрос или задачу:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📜 История", callback_data=f"proj_{key}_history"),
                InlineKeyboardButton("🚪 Выйти из проекта", callback_data="menu"),
            ]])
        )

    elif data.startswith("proj_") and data.endswith("_history"):
        key = data[5:-8]
        if key not in PROJECTS: return
        p = PROJECTS[key]
        h = get_proj_history(uid, key)
        if not h:
            await q.edit_message_text(
                f"{p['emoji']} *{p['name']}* — история пуста\n\nНачни диалог кнопкой «Открыть диалог»",
                parse_mode="Markdown",
                reply_markup=project_keyboard(key)
            )
            return
        # Показываем последние 5 пар
        pairs, i = [], 0
        while i < len(h):
            if h[i].get("role") == "user":
                u = h[i]["content"][:100] + ("…" if len(h[i]["content"]) > 100 else "")
                b = ""
                if i+1 < len(h) and h[i+1].get("role") == "assistant":
                    b = h[i+1]["content"][:150] + ("…" if len(h[i+1]["content"]) > 150 else "")
                    i += 2
                else: i += 1
                pairs.append((u, b))
        last = pairs[-5:]
        lines = [f"{p['emoji']} *История: {p['name']}*\n"]
        for n, (u, b) in enumerate(last, 1):
            lines.append(f"*{n}. Ты:* {u}")
            if b: lines.append(f"*🤖:* {b}\n")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Продолжить диалог", callback_data=f"proj_{key}_chat")],
                [InlineKeyboardButton("🗑 Очистить", callback_data=f"proj_{key}_clear")],
                [InlineKeyboardButton("◀️ К проекту", callback_data=f"proj_{key}")],
            ])
        )

    elif data.startswith("proj_") and data.endswith("_clear"):
        key = data[5:-6]
        if key not in PROJECTS: return
        set_proj_history(uid, key, [])
        await q.edit_message_text(
            f"✅ История проекта *{PROJECTS[key]['name']}* очищена",
            parse_mode="Markdown",
            reply_markup=project_keyboard(key)
        )

    # ── Заметки ──
    elif data == "notes":
        user_notes = get_notes(uid)
        if not user_notes:
            await q.edit_message_text(
                "📓 *Заметок пока нет*\n\nНапиши боту: _«сохрани заметку: текст»_",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
            return
        lines = ["📓 *Заметки:*\n"]
        for i, n in enumerate(user_notes[:10], 1):
            lines.append(f"*{i}. {n['title']}*\n_{n['summary']}_\n🕐 {n['date']}\n")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Очистить", callback_data="notes_clear")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "notes_clear":
        notes[str(uid)] = []
        save_notes()
        await q.edit_message_text("✅ Заметки очищены", reply_markup=back_keyboard())

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

    # ── Серверы ──
    elif data == "servers":
        await q.edit_message_text("🖥 *Выбери сервер:*", parse_mode="Markdown", reply_markup=servers_keyboard())

    elif data.startswith("srv_") and data.count("_") == 1:
        key = data[4:]
        srv = SERVERS.get(key, {})
        await q.edit_message_text(f"{srv.get('label','?')}\n`{srv.get('host','')}`", parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_status"):
        key = data[4:-7]
        srv = SERVERS.get(key, {})
        await q.edit_message_text(f"⏳ Проверяю...")
        lines = [f"📊 *{srv.get('label','?')}*\n"]
        for svc in srv.get("services", []):
            out = ssh_exec(key, f"systemctl is-active {svc}")
            lines.append(f"{'🟢' if 'active' in out else '🔴'} `{svc}`")
        lines += [f"\n⏱ {ssh_exec(key,'uptime -p')}", f"💾 {ssh_exec(key,\"free -h | awk 'NR==2{print $3\\\"/\\\"$2}'\")}" ]
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_logs"):
        key = data[4:-5]
        srv = SERVERS.get(key, {})
        svc = srv.get("services", [""])[0]
        logs = ssh_exec(key, f"journalctl -u {svc} -n 15 --no-pager -o short 2>/dev/null")
        await q.edit_message_text(f"```\n{logs}\n```", parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_restart"):
        key = data[4:-8]
        srv = SERVERS.get(key, {})
        if not is_super(uid):
            await q.answer("⛔ Только суперадмины", show_alert=True)
            return
        results = []
        for svc in srv.get("services", []):
            out = ssh_exec(key, f"systemctl restart {svc} && echo OK")
            results.append(f"{'✅' if 'OK' in out else '❌'} `{svc}`")
        await q.edit_message_text("\n".join(results), parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_disk"):
        key = data[4:-5]
        disk = ssh_exec(key, "df -h / | tail -1")
        await q.edit_message_text(f"```\n{disk}\n```", parse_mode="Markdown", reply_markup=server_keyboard(key))

    elif data.endswith("_custom"):
        key = data[4:-7]
        srv = SERVERS.get(key, {})
        ctx.user_data["waiting_for"] = f"ssh_{key}"
        await q.edit_message_text(f"⌨️ Введи команду для *{srv.get('label','?')}*:", parse_mode="Markdown", reply_markup=back_keyboard(f"srv_{key}"))

    # ── Прочее ──
    elif data == "myid":
        await q.edit_message_text(f"📋 Твой ID:\n\n`{uid}`", parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "show_system":
        system = get_system(uid)
        await q.edit_message_text(f"⚙️ *Системный промпт:*\n\n_{system}_", parse_mode="Markdown",
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
    proj_key = ctx.user_data.get("project")

    # ── SSH ──
    if waiting and waiting.startswith("ssh_"):
        ctx.user_data.pop("waiting_for")
        key = waiting[4:]
        await update.message.reply_text(f"⏳ `{text}`", parse_mode="Markdown")
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
        await update.message.reply_text(f"✅ Промпт: _{text}_", parse_mode="Markdown", reply_markup=main_keyboard(uid))
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

    # ── Ручная заметка ──
    if text.lower().startswith(("сохрани заметку:", "запомни:")):
        content = text.split(":", 1)[1].strip()
        add_note(uid, "📝 Заметка", content)
        await update.message.reply_text("✅ Заметка сохранена!", reply_markup=main_keyboard(uid))
        return

    # ── Диалог (проектный или общий) ──
    if proj_key and proj_key in PROJECTS:
        p = PROJECTS[proj_key]
        system_prompt = p["system"]
        messages = get_proj_history(uid, proj_key)
    else:
        proj_key = None
        h = get_history(uid)
        system_prompt = DEFAULT_SYSTEM
        for m in h:
            if m.get("_type") == "system": system_prompt = m["content"]
        messages = [m for m in h if m.get("_type") != "system"]

    messages = list(messages)
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
        await update.message.reply_text(f"❌ `{e}`", parse_mode="Markdown")
        return

    messages.append({"role": "assistant", "content": reply})

    if proj_key:
        set_proj_history(uid, proj_key, messages)
    else:
        h = get_history(uid)
        system_entries = [m for m in h if m.get("_type") == "system"]
        set_history(uid, system_entries + messages)

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            is_last = i + 4000 >= len(reply)
            await update.message.reply_text(reply[i:i+4000], reply_markup=chat_keyboard(proj_key) if is_last else None)
    else:
        await update.message.reply_text(reply, reply_markup=chat_keyboard(proj_key))

    log.info(f"OK | user={uid} | proj={proj_key or 'general'} | in={len(text)}ch | out={len(reply)}ch")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN: print("❌ TELEGRAM_TOKEN не задан"); return
    if not ANTHROPIC_KEY:  print("❌ ANTHROPIC_KEY не задан"); return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("✅ Bot started with Projects + Notes + SSH")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
