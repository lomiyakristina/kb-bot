FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Secrets stay out of the image: TELEGRAM_TOKEN and OWNER_CHAT_ID via Amvera env.
COPY bot.py /app/bot.py
COPY faq.json /app/faq.json

CMD ["python", "bot.py", "run"]
