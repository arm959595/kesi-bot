import os
import json
import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = os.environ.get("BOT_TOKEN")
GROUP_NAME = "ДЮ-9-2025, ДЮ-11-26"
URL = "https://college-edu.ru/stud/raspisanie/"
SUBSCRIBERS_FILE = "subscribers.json"
MOSCOW = ZoneInfo("Europe/Moscow")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subs), f)

subscribers = load_subscribers()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server on port {PORT}")
    server.serve_forever()

def get_schedule():
    try:
        r = requests.get(URL, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        target = None
        for h2 in soup.find_all("h2"):
            if GROUP_NAME in h2.get_text():
                target = h2
                break
        if not target:
            return {}
        days = {}
        for sib in target.find_next_siblings():
            if sib.name == "h2":
                break
            if sib.name == "div" and "rasp__day" in (sib.get("class") or []):
                day_el = sib.find("h3")
                if not day_el:
                    continue
                day_text = day_el.get_text(strip=True)
                pairs = []
                for pair in sib.find_all("div", class_="rasp__pair"):
                    time_el = pair.find("div", class_="rasp__time")
                    subj = pair.find("div", class_="rasp__subj")
                    info = pair.find("div", class_="rasp__info")
                    teach = info.find("span", class_="rasp__teach") if info else None
                    aud = info.find("span", class_="rasp__aud") if info else None
                    num = time_el.find("b").get_text(strip=True) if time_el and time_el.find("b") else ""
                    tm = time_el.find("span").get_text(strip=True) if time_el and time_el.find("span") else ""
                    pairs.append({
                        "num": num, "time": tm,
                        "subj": subj.get_text(strip=True) if subj else "",
                        "teach": teach.get_text(strip=True) if teach else "",
                        "aud": aud.get_text(strip=True) if aud else ""
                    })
                days[day_text] = pairs
        return days
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return {}

def format_day(day_name, pairs):
    if not pairs:
        return f"📅 {day_name}\n\nПар нет 🎉"
    lines = [f"📅 <b>{day_name}</b>\n"]
    for p in pairs:
        line = f"<b>{p['num']} пара</b> ({p['time']})\n{p['subj']}"
        if p["teach"]:
            line += f"\n👤 {p['teach']}"
        if p["aud"]:
            line += f"\n🚪 {p['aud']}"
        lines.append(line)
    return "\n\n".join(lines)

def get_day_key(target_date):
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    wd = weekdays[target_date.weekday()]
    return f"{wd}, {target_date.strftime('%d.%m.%y')}"

def get_schedule_for(date):
    days = get_schedule()
    key = get_day_key(date)
    if key in days:
        return format_day(key, days[key])
    for k, v in days.items():
        if k.startswith(key[:2]):
            return format_day(k, v)
    return f"📅 {key}\n\nРасписание на этот день не найдено."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers.add(chat_id)
    save_subscribers(subscribers)
    await update.message.reply_text(
        "Привет! Я бот расписания КЭСИ (группа ДЮ-9-25).\n\n"
        "Команды:\n• сегодня / /сегодня\n• завтра / /завтра\n\n"
        "Каждый день в 21:00 присылаю расписание на завтра."
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(MOSCOW)
    text = get_schedule_for(now.date())
    await update.message.reply_text(text, parse_mode="HTML")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(MOSCOW)
    text = get_schedule_for(now.date() + timedelta(days=1))
    await update.message.reply_text(text, parse_mode="HTML")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    if "сегодня" in text:
        await today(update, context)
    elif "завтра" in text:
        await tomorrow(update, context)
    else:
        await update.message.reply_text("Напиши «сегодня» или «завтра»")

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(MOSCOW)
    text = "🔔 Расписание на завтра:\n\n" + get_schedule_for(now.date() + timedelta(days=1))
    for chat_id in list(subscribers):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить {chat_id}: {e}")
            subscribers.discard(chat_id)
    save_subscribers(subscribers)

def main():
    # Запускаем health-сервер в отдельном потоке
    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("сегодня", today))
    app.add_handler(CommandHandler("завтра", tomorrow))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    scheduler = AsyncIOScheduler(timezone=MOSCOW)
    scheduler.add_job(daily_job, "cron", hour=21, minute=0, args=[app])
    scheduler.start()

    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
