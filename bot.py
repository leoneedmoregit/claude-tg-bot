import os, json, logging, paramiko, threading
from io import StringIO
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

DEFAULT_SYSTEM = (
    "Ты умный помощник и DevOps-ассистент. Отвечай на русском языке. "
    "Ты работаешь в Telegram-боте и можешь управлять серверами через SSH. "
    "Когда пользователь просит что-то сделать на сервере — предлагай конкретные команды."
)

SUPER_ADMINS = {270589758, 108863518}

# ─── СЕРВЕРЫ ──────────────────────────────────────────────────────────────────
SERVERS = {
    "ferma": {
        "label": "🌾 ФЕРМА",
        "host": "195.123.228.234",
        "user": "root",
        "password": os.environ.get("FERMA_PASS", ""),
        "services": ["claude-bot", "ferma_server"],
        "projects": ["/root/claude_bot", "/root/ferma_server.py"],
    },
    "obshchee": {
        "label": "🤝 Общее Дело",
        "host": "85.90.197.57",
        "user": "root",
        "password": os.environ.get("OBSHCHEE_PASS", ""),
        "services": ["obshchee-delo"],
        "projects": ["/opt/obshchee-delo"],
    },
}

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── ХРАНИЛИЩЕ ────────────────────────────────────────────────────────────────
def load_admins():
    try:
        with open(ADMINS_FILE) as f: return set(json.load(f))
    except: return set()

def save_admins(a):
    with open(ADMINS_FILE, "w") as f: json.dump(list(a), f)

def load_histories():
    try:
        with open(HISTORY_FILE) as f: return json.load(f)
    except: return {}

def save_histories(h):
    with open(HISTORY_FILE, "w") as f: json.dump(h, f, ensure_ascii=False)

admins    = load_admins() | SUPER_ADMINS
histories = load_histories()
client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def is_admin(uid): return uid in admins or uid in SUPER_ADMINS
def is_super(uid): return uid in SUPER_ADMINS

def get_history(uid):
    return histories.get(str(uid), [])

def set_history(uid, h):
    histories[str(uid)] = h[-40:]
    save_histories(histories)

def get_system(uid):
    for m in get_history(uid):
        if m.get("_type") == "system":
            return m["content"]
    return DEFAULT_SYSTEM

def get_dialog(uid):
    return [m for m in get_history(uid) if m.get("_type") != "system"]

# ─── SSH ──────────────────────────────────────────────────────────────────────
def ssh_exec(server_key: str, command: str, timeout: int = 30) -> str:
    srv = SERVERS.get(server_key)
    if not srv:
        return f"❌ Сервер '{server_key}' не найден"
    if not srv["password"]:
        return f"❌ Пароль для {srv['label']} не задан"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            srv["host"], port=22,
            username=srv["user"],
            password=srv["password"],
            timeout=10
        )
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        ssh.close()
        result = out
        if err and not out:
            result = err
        elif err:
            result = out + "\n⚠️ stderr:\n" + err
        return result[:3500] if result else "✅ Команда выполнена (нет вывода)"
    except Exception as e:
        return f"❌ SSH ошибка: {e}"

def get_service_status(server_key: str, service: str) -> str:
    out = ssh_exec(server_key, f"systemctl is-active {service} 2>/dev/null")
    if "active" in out:
        return "🟢"
    elif "inactive" in out:
        return "🔴"
    else:
        return "🟡"

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def main_keyboard(uid):
    buttons = [
        [
            InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
            InlineKeyboardButton("📜 История", callback_data="history"),
        ],
        [
            InlineKeyboardButton("⚙️ Промпт", callback_data="show_system"),
            InlineKeyboardButton("🗑 Очистить", callback_data="clear"),
        ],
        [
            InlineKeyboardButton("🌐 Claude.ai", url="https://claude.ai"),
        InlineKeyboardButton("📚 Диалоги", url="http://195.123.228.234:8080/history.html"),
            InlineKeyboardButton("📋 Мой ID", callback_data="myid"),
        ],
    ]
    if is_admin(uid):
        buttons.append([
            InlineKeyboardButton("👥 Админы", callback_data="admins"),
            InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt"),
        ])
    return InlineKeyboardMarkup(buttons)

def servers_keyboard():
    buttons = []
    for key, srv in SERVERS.items():
        buttons.append([InlineKeyboardButton(srv["label"], callback_data=f"srv_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)

def server_keyboard(key):
    srv = SERVERS[key]
    buttons = [
        [
            InlineKeyboardButton("📊 Статус сервисов", callback_data=f"srv_{key}_status"),
            InlineKeyboardButton("📋 Логи", callback_data=f"srv_{key}_logs"),
        ],
        [
            InlineKeyboardButton("🔄 Рестарт всех", callback_data=f"srv_{key}_restart"),
            InlineKeyboardButton("💾 Диск", callback_data=f"srv_{key}_disk"),
        ],
        [InlineKeyboardButton("⌨️ Своя команда", callback_data=f"srv_{key}_custom")],
        [InlineKeyboardButton("◀️ Серверы", callback_data="servers")],
    ]
    return InlineKeyboardMarkup(buttons)

def back_keyboard(to="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=to)]])

# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.effective_user.first_name or "незнакомец"
    if not is_admin(user_id):
        await update.message.reply_text(
            f"⛔ Доступ закрыт.\n\nТвой ID: `{user_id}`",
            parse_mode="Markdown"
        )
        return
    role = "👑 суперадмин" if is_super(user_id) else "🔑 администратор"
    dialog = get_dialog(user_id)
    msg_count = len([m for m in dialog if m["role"] == "user"])
    await update.message.reply_text(
        f"Привет, *{name}*! Ты — {role}\n\n"
        f"📊 Сообщений в истории: *{msg_count}*\n"
        f"🖥 Серверов подключено: *{len(SERVERS)}*\n\n"
        "Пиши мне — я отвечу и помогу управлять серверами:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )

# ─── CALLBACK ─────────────────────────────────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = q.data

    if not is_admin(user_id):
        await q.answer("⛔ Нет доступа", show_alert=True)
        return

    # ── Главное меню ──
    if data == "menu":
        name = q.from_user.first_name or "незнакомец"
        role = "👑 суперадмин" if is_super(user_id) else "🔑 администратор"
        dialog = get_dialog(user_id)
        msg_count = len([m for m in dialog if m["role"] == "user"])
        await q.edit_message_text(
            f"Привет, *{name}*! Ты — {role}\n\n"
            f"📊 Сообщений в истории: *{msg_count}*\n"
            f"🖥 Серверов подключено: *{len(SERVERS)}*\n\n"
            "Пиши мне — я отвечу и помогу управлять серверами:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(user_id)
        )

    # ── Список серверов ──
    elif data == "servers":
        await q.edit_message_text(
            "🖥 *Выбери сервер:*",
            parse_mode="Markdown",
            reply_markup=servers_keyboard()
        )

    # ── Конкретный сервер ──
    elif data.startswith("srv_") and data.count("_") == 1:
        key = data[4:]
        srv = SERVERS.get(key)
        if not srv:
            await q.edit_message_text("❌ Сервер не найден", reply_markup=back_keyboard("servers"))
            return
        await q.edit_message_text(
            f"{srv['label']}\n\n"
            f"🌐 `{srv['host']}`\n"
            f"👤 `{srv['user']}`\n"
            f"📁 Проекты: {', '.join(srv['projects'])}\n\n"
            "Выбери действие:",
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    # ── Статус сервисов ──
    elif data.endswith("_status"):
        key = data[4:-7]
        srv = SERVERS.get(key)
        if not srv:
            return
        await q.edit_message_text(f"⏳ Проверяю статус {srv['label']}...", parse_mode="Markdown")
        lines = [f"📊 *Статус сервисов {srv['label']}:*\n"]
        for svc in srv["services"]:
            status = get_service_status(key, svc)
            lines.append(f"{status} `{svc}`")
        # Общая нагрузка
        uptime = ssh_exec(key, "uptime | awk -F'load average:' '{print $2}'")
        lines.append(f"\n📈 Нагрузка: `{uptime}`")
        mem = ssh_exec(key, "free -h | awk 'NR==2{print $3\"/\"$2}'")
        lines.append(f"💾 RAM: `{mem}`")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    # ── Логи ──
    elif data.endswith("_logs"):
        key = data[4:-5]
        srv = SERVERS.get(key)
        if not srv:
            return
        await q.edit_message_text(f"⏳ Получаю логи {srv['label']}...")
        svc = srv["services"][0]
        logs = ssh_exec(key, f"journalctl -u {svc} -n 30 --no-pager -o short 2>/dev/null | tail -20")
        await q.edit_message_text(
            f"📋 *Логи {svc}:*\n\n```\n{logs}\n```",
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    # ── Рестарт ──
    elif data.endswith("_restart"):
        key = data[4:-8]
        srv = SERVERS.get(key)
        if not srv:
            return
        if not is_super(user_id):
            await q.answer("⛔ Только суперадмины", show_alert=True)
            return
        await q.edit_message_text(f"🔄 Перезапускаю сервисы {srv['label']}...")
        results = []
        for svc in srv["services"]:
            out = ssh_exec(key, f"systemctl restart {svc} && echo OK")
            results.append(f"{'✅' if 'OK' in out else '❌'} `{svc}`")
        await q.edit_message_text(
            f"🔄 *Рестарт {srv['label']}:*\n\n" + "\n".join(results),
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    # ── Диск ──
    elif data.endswith("_disk"):
        key = data[4:-5]
        srv = SERVERS.get(key)
        if not srv:
            return
        await q.edit_message_text(f"⏳ Проверяю диск {srv['label']}...")
        disk = ssh_exec(key, "df -h / | tail -1")
        await q.edit_message_text(
            f"💾 *Диск {srv['label']}:*\n\n```\n{disk}\n```",
            parse_mode="Markdown",
            reply_markup=server_keyboard(key)
        )

    # ── Своя команда ──
    elif data.endswith("_custom"):
        key = data[4:-7]
        srv = SERVERS.get(key)
        ctx.user_data["waiting_for"] = f"ssh_{key}"
        await q.edit_message_text(
            f"⌨️ *Введи команду для {srv['label']}:*\n\n"
            "Например: `systemctl status claude-bot`\n"
            "или: `tail -20 /root/claude_bot/bot.log`",
            parse_mode="Markdown",
            reply_markup=back_keyboard(f"srv_{key}")
        )

    # ── История ──
    elif data == "history":
        dialog = get_dialog(user_id)
        if not dialog:
            await q.edit_message_text("📭 История пуста!", reply_markup=back_keyboard())
            return
        pairs = []
        i = 0
        while i < len(dialog):
            if dialog[i]["role"] == "user":
                u = dialog[i]["content"][:80] + ("…" if len(dialog[i]["content"]) > 80 else "")
                b = ""
                if i+1 < len(dialog) and dialog[i+1]["role"] == "assistant":
                    b = dialog[i+1]["content"][:100] + ("…" if len(dialog[i+1]["content"]) > 100 else "")
                    i += 2
                else:
                    i += 1
                pairs.append((u, b))
        last = pairs[-5:]
        lines = [f"📜 *Последние {len(last)} сообщений:*\n"]
        for n, (u, b) in enumerate(last, 1):
            lines.append(f"*{n}. Ты:* {u}")
            if b: lines.append(f"*🤖:* {b}\n")
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Очистить", callback_data="clear")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "clear":
        h = [m for m in get_history(user_id) if m.get("_type") == "system"]
        set_history(user_id, h)
        await q.edit_message_text("✅ История очищена!", reply_markup=back_keyboard())

    elif data == "myid":
        await q.edit_message_text(
            f"📋 Твой ID:\n\n`{user_id}`",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )

    elif data == "show_system":
        system = get_system(user_id)
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
        await q.edit_message_text(
            "✏️ Введи новый системный промпт:",
            reply_markup=back_keyboard()
        )

    elif data == "system_reset":
        h = [m for m in get_history(user_id) if m.get("_type") != "system"]
        set_history(user_id, h)
        await q.edit_message_text("✅ Промпт сброшен к дефолтному", reply_markup=back_keyboard())

    elif data == "admins":
        lines = ["👑 *Суперадмины:*"] + [f"  `{i}`" for i in sorted(SUPER_ADMINS)]
        regular = admins - SUPER_ADMINS
        if regular:
            lines += ["\n🔑 *Администраторы:*"] + [f"  `{i}`" for i in sorted(regular)]
        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data="addadmin_prompt")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
            ])
        )

    elif data == "addadmin_prompt":
        ctx.user_data["waiting_for"] = "addadmin"
        await q.edit_message_text(
            "➕ Введи Telegram ID нового администратора:",
            reply_markup=back_keyboard()
        )

# ─── СООБЩЕНИЯ ────────────────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(f"⛔ Доступ закрыт. Твой ID: `{user_id}`", parse_mode="Markdown")
        return

    text = update.message.text
    waiting = ctx.user_data.get("waiting_for")

    # ── SSH команда ──
    if waiting and waiting.startswith("ssh_"):
        ctx.user_data.pop("waiting_for")
        key = waiting[4:]
        srv = SERVERS.get(key)
        await update.message.reply_text(f"⏳ Выполняю на {srv['label']}:\n`{text}`", parse_mode="Markdown")
        result = ssh_exec(key, text)
        await update.message.reply_text(
            f"```\n{result}\n```",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🖥 Обратно к серверу", callback_data=f"srv_{key}"),
                InlineKeyboardButton("☰ Меню", callback_data="menu"),
            ]])
        )
        return

    # ── Системный промпт ──
    if waiting == "system_prompt":
        ctx.user_data.pop("waiting_for")
        h = [m for m in get_history(user_id) if m.get("_type") != "system"]
        h.insert(0, {"_type": "system", "content": text})
        set_history(user_id, h)
        await update.message.reply_text(f"✅ Промпт обновлён:\n_{text}_", parse_mode="Markdown", reply_markup=main_keyboard(user_id))
        return

    # ── Добавить админа ──
    if waiting == "addadmin":
        ctx.user_data.pop("waiting_for")
        try:
            new_id = int(text.strip())
            admins.add(new_id)
            save_admins(admins)
            await update.message.reply_text(f"✅ `{new_id}` добавлен как администратор!", parse_mode="Markdown", reply_markup=main_keyboard(user_id))
        except:
            await update.message.reply_text("❌ Неверный ID", reply_markup=main_keyboard(user_id))
        return

    # ── Диалог с Claude ──
    h = get_history(user_id)
    system_prompt = DEFAULT_SYSTEM
    messages = []
    for m in h:
        if m.get("_type") == "system": system_prompt = m["content"]
        else: messages.append(m)

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
        await update.message.reply_text(f"❌ Ошибка API: `{e}`", parse_mode="Markdown")
        return

    messages.append({"role": "assistant", "content": reply})
    system_entries = [m for m in h if m.get("_type") == "system"]
    set_history(user_id, system_entries + messages)

    reply_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🖥 Серверы", callback_data="servers"),
        InlineKeyboardButton("📜 История", callback_data="history"),
        InlineKeyboardButton("☰ Меню", callback_data="menu"),
    ]])

    if len(reply) > 4000:
        for i in range(0, len(reply), 4000):
            is_last = i + 4000 >= len(reply)
            await update.message.reply_text(reply[i:i+4000], reply_markup=reply_kb if is_last else None)
    else:
        await update.message.reply_text(reply, reply_markup=reply_kb)

    log.info(f"OK | user={user_id} | in={len(text)}ch | out={len(reply)}ch")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN: print("❌ TELEGRAM_TOKEN не задан"); return
    if not ANTHROPIC_KEY:  print("❌ ANTHROPIC_KEY не задан"); return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Bot started with SSH support")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
