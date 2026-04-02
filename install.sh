#!/bin/bash
set -e

# ─── ЦВЕТА ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}"
echo "╔══════════════════════════════════════╗"
echo "║   Claude Telegram Bot — Установка   ║"
echo "╚══════════════════════════════════════╝"
echo -e "${NC}"

# ─── ТОКЕНЫ ───────────────────────────────────────────────
if [ -z "$TELEGRAM_TOKEN" ]; then
  echo -e "${YELLOW}Введи Telegram Bot Token (от @BotFather):${NC}"
  read -r TELEGRAM_TOKEN
fi

if [ -z "$ANTHROPIC_KEY" ]; then
  echo -e "${YELLOW}Введи Anthropic API Key (sk-ant-...):${NC}"
  read -r ANTHROPIC_KEY
fi

# ─── УСТАНОВКА ────────────────────────────────────────────
echo -e "\n${GREEN}[1/5] Создаю папку...${NC}"
mkdir -p /root/claude_bot
cd /root/claude_bot

echo -e "${GREEN}[2/5] Скачиваю файлы...${NC}"
curl -fsSL https://raw.githubusercontent.com/leoneedmoregit/claude-tg-bot/main/bot.py -o bot.py

echo -e "${GREEN}[3/5] Устанавливаю зависимости...${NC}"
apt-get install -y python3-pip -q
pip3 install python-telegram-bot==21.5 anthropic -q --break-system-packages 2>/dev/null || \
pip3 install python-telegram-bot==21.5 anthropic -q

echo -e "${GREEN}[4/5] Создаю конфиг запуска...${NC}"
cat > /root/claude_bot/start.sh << EOF
#!/bin/bash
export TELEGRAM_TOKEN="${TELEGRAM_TOKEN}"
export ANTHROPIC_KEY="${ANTHROPIC_KEY}"
cd /root/claude_bot
python3 bot.py >> bot.log 2>&1
EOF
chmod +x /root/claude_bot/start.sh

echo -e "${GREEN}[5/5] Регистрирую службу systemd...${NC}"
cat > /etc/systemd/system/claude-bot.service << EOF
[Unit]
Description=Claude Telegram Bot
After=network.target

[Service]
ExecStart=/bin/bash /root/claude_bot/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable claude-bot
systemctl start claude-bot

sleep 2
STATUS=$(systemctl is-active claude-bot)

echo ""
if [ "$STATUS" = "active" ]; then
  echo -e "${GREEN}✅ Бот успешно запущен и будет автоматически стартовать при перезагрузке!${NC}"
  echo -e "Логи: ${YELLOW}tail -f /root/claude_bot/bot.log${NC}"
  echo -e "Статус: ${YELLOW}systemctl status claude-bot${NC}"
  echo -e "Остановить: ${YELLOW}systemctl stop claude-bot${NC}"
else
  echo -e "${RED}❌ Что-то пошло не так. Смотри логи:${NC}"
  journalctl -u claude-bot -n 20
fi
