#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Бот-консультант «Красногорские бани» (Лумо).
Чистый Python, без внешних зависимостей.

Режимы запуска:
  python bot.py whoami     - проверить токен (кто этот бот)
  python bot.py getchat    - найти chat_id Шефа из последних сообщений боту и сохранить
  python bot.py notify "текст"  - отправить сообщение Шефу (уведомление)
  python bot.py run        - запустить бота для клиентов (long polling)  [наружу!]

Токен читается из ../../vault/telegram.txt
FAQ/сценарий — из faq.json (рядом с этим файлом).
chat_id Шефа сохраняется в owner_chat_id.txt (рядом).
Заявки клиентов дублируются в leads.log (рядом).
"""

import json
import os
import sys
import time
import re
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
TOKEN_FILE = os.path.join(ROOT, "vault", "telegram.txt")
FAQ_FILE = os.path.join(BASE_DIR, "faq.json")
OWNER_FILE = os.path.join(BASE_DIR, "owner_chat_id.txt")
LEADS_FILE = os.path.join(BASE_DIR, "leads.log")

PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{6,}\d)")
LEAD_WORDS = ("хочу", "открыт", "запиш", "контакт", "телефон", "звон", "перезвон", "связ")


def read_token():
    # В облаке токен берём из секретной переменной окружения,
    # локально — из vault/telegram.txt
    env = os.environ.get("TELEGRAM_TOKEN")
    if env:
        return env.strip()
    with open(TOKEN_FILE, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def load_faq():
    with open(FAQ_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def api(method, params=None):
    token = read_token()
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = None
    if params is not None:
        data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_owner():
    env = os.environ.get("OWNER_CHAT_ID")
    if env:
        return env.strip()
    if os.path.exists(OWNER_FILE):
        with open(OWNER_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
            return v or None
    return None


def save_owner(chat_id):
    with open(OWNER_FILE, "w", encoding="utf-8") as f:
        f.write(str(chat_id))


def inline_keyboard(faq):
    rows = [[{"text": b["text"], "callback_data": b["data"]}] for b in faq["buttons"]]
    return json.dumps({"inline_keyboard": rows})


def send_message(chat_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "text": text}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return api("sendMessage", params)


def notify_owner(text):
    owner = get_owner()
    if not owner:
        print("Нет сохранённого chat_id Шефа. Сначала: python bot.py getchat")
        return False
    send_message(owner, text)
    return True


def log_lead(line):
    with open(LEADS_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def cmd_whoami():
    print(json.dumps(api("getMe"), ensure_ascii=False, indent=2))


def cmd_getchat():
    res = api("getUpdates", {"offset": 0, "limit": 50})
    chats = {}
    for upd in res.get("result", []):
        msg = upd.get("message") or upd.get("callback_query", {}).get("message")
        frm = (upd.get("message") or upd.get("callback_query") or {}).get("from", {})
        if msg and msg.get("chat", {}).get("type") == "private":
            cid = msg["chat"]["id"]
            name = (frm.get("first_name", "") + " " + frm.get("last_name", "")).strip()
            uname = frm.get("username", "")
            chats[cid] = "%s (@%s)" % (name, uname) if uname else name
    if not chats:
        print("Никто ещё не писал боту. Открой @Krasnogorskie_bani_bot, нажми Start и напиши «привет», потом запусти снова.")
        return
    print("Найдены чаты:")
    for cid, who in chats.items():
        print("  %s — %s" % (cid, who))
    if len(chats) == 1:
        cid = list(chats.keys())[0]
        save_owner(cid)
        print("Сохранил chat_id Шефа: %s" % cid)
    else:
        print("Чатов несколько. Запиши нужный id в owner_chat_id.txt вручную.")


def cmd_notify(text):
    if notify_owner(text):
        print("Отправлено Шефу.")


def cmd_run():
    faq = load_faq()
    kb = inline_keyboard(faq)
    owner = get_owner()
    me = api("getMe")["result"]
    print("Бот @%s запущен. Ctrl+C для остановки." % me.get("username"))
    if not owner:
        print("ВНИМАНИЕ: chat_id Шефа не задан — заявки не будут пересылаться. Сделай: python bot.py getchat")
    awaiting = set()  # chat_id, от кого ждём контакт
    offset = 0
    while True:
        try:
            res = api("getUpdates", {"offset": offset, "timeout": 30})
        except Exception as e:
            print("Ошибка сети:", e)
            time.sleep(3)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            try:
                handle_update(upd, faq, kb, awaiting)
            except Exception as e:
                print("Ошибка обработки:", e)


def forward_lead(faq, frm, chat_id, text):
    name = (frm.get("first_name", "") + " " + frm.get("last_name", "")).strip()
    uname = frm.get("username", "")
    who = "%s (@%s)" % (name, uname) if uname else (name or str(chat_id))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    log_lead("%s | %s | %s" % (stamp, who, text.replace("\n", " ")))
    notify_owner("🔥 Новая заявка с бота Красногорских бань\n\nОт: %s\nСообщение: %s" % (who, text))
    send_message(chat_id, faq["lead_thanks"])


def handle_update(upd, faq, kb, awaiting):
    if "callback_query" in upd:
        cq = upd["callback_query"]
        data = cq.get("data")
        chat_id = cq["message"]["chat"]["id"]
        api("answerCallbackQuery", {"callback_query_id": cq["id"]})
        if data in ("waitlist", "contact"):
            awaiting.add(chat_id)
            send_message(chat_id, faq["answers"][data])
        elif data in faq["answers"]:
            send_message(chat_id, faq["answers"][data], reply_markup=kb)
        return

    msg = upd.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    frm = msg.get("from", {})
    text = msg.get("text", "") or ""

    if text.startswith("/start"):
        send_message(chat_id, faq["greeting"], reply_markup=kb)
        return

    low = text.lower()
    is_lead = (
        chat_id in awaiting
        or PHONE_RE.search(text) is not None
        or any(w in low for w in LEAD_WORDS)
    )
    if is_lead:
        awaiting.discard(chat_id)
        forward_lead(faq, frm, chat_id, text)
    else:
        send_message(chat_id, faq["fallback"], reply_markup=kb)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "whoami":
        cmd_whoami()
    elif cmd == "getchat":
        cmd_getchat()
    elif cmd == "notify":
        cmd_notify(" ".join(sys.argv[2:]) or "Тест уведомления от Зены ✅")
    elif cmd == "run":
        cmd_run()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
