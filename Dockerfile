FROM python:3.12-slim

WORKDIR /app

# Копируем только мозги бота — vault и секреты НЕ попадают в образ.
# Токен и chat_id задаются переменными окружения TELEGRAM_TOKEN и OWNER_CHAT_ID.
COPY bot.py /app/bot.py
COPY faq.json /app/faq.json

CMD ["python", "bot.py", "run"]
