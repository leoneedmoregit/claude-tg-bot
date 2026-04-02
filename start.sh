#!/bin/bash
export TELEGRAM_TOKEN="ВСТАВЬ_ТОКЕН_СЮДА"
export ANTHROPIC_KEY="ВСТАВЬ_КЛЮЧ_СЮДА"
cd /root/claude_bot
python3 bot.py >> bot.log 2>&1
