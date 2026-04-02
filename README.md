# Claude Telegram Bot 🤖

Telegram-бот с Claude AI внутри. Поддержка администраторов, история диалогов, настройка системного промпта.

## Быстрая установка (одна команда)

```bash
curl -fsSL https://raw.githubusercontent.com/GITHUB_USER/REPO_NAME/main/install.sh | bash
```

Скрипт сам спросит токены и всё настроит.

## Команды бота

| Команда | Кто | Действие |
|---|---|---|
| `/start`, `/help` | все | справка |
| `/myid` | все | показать свой Telegram ID |
| `/clear` | все | очистить историю |
| `/system текст` | админ | задать системный промпт |
| `/mysystem` | админ | посмотреть промпт |
| `/addadmin ID` | любой админ | выдать права |
| `/deladmin ID` | суперадмин | забрать права |
| `/admins` | любой админ | список всех |

## Управление на сервере

```bash
systemctl status claude-bot   # статус
systemctl restart claude-bot  # перезапуск
systemctl stop claude-bot     # остановить
tail -f /root/claude_bot/bot.log  # логи
```
