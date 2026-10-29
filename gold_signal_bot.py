import asyncio
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import pandas as pd
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
SYMBOL = "GC=F"       
INTERVAL = "5m"       
PERIOD = "5d"
CHECK_EVERY = 300     
ATR_SL = 1.5          
RR = 2.0              

logging.basicConfig(level=logging.INFO)

# --- ส่วนเพิ่มสำหรับ Cloud: เปิดเว็บพอร์ตเพื่อให้ Render ผ่าน Health Check ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gold Signal Bot is running!")
    
    def log_message(self, format, *args):
        pass 

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def fetch() -> pd.DataFrame:
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL,
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["Close"], df["High"], df["Low"]
    df["ema9"] = c.ewm(span=9, adjust=False).mean()
    df["ema21"] = c.ewm(span=21, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)

    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df

def get_signal(df: pd.DataFrame):
    if len(df) < 60:
        return None
    last, prev = df.iloc[-2], df.iloc[-3]
    price, atr = float(last["Close"]), float(last["atr"])
    risk = atr * ATR_SL

    cross_up = prev["ema9"] <= prev["ema21"] and last["ema9"] > last["ema21"]
    cross_dn = prev["ema9"] >= prev["ema21"] and last["ema9"] < last["ema21"]

    side = None
    if cross_up and price > last["ema50"] and 50 <= last["rsi"] <= 70:
        side = "BUY"
        sl, tp = price - risk, price + risk * RR
    elif cross_dn and price < last["ema50"] and 30 <= last["rsi"] <= 50:
        side = "SELL"
        sl, tp = price + risk, price - risk * RR
    if not side:
        return None

    return {
        "side": side, "entry": price, "sl": sl, "tp": tp,
        "rsi": float(last["rsi"]), "time": str(df.index[-2]),
    }

def format_signal(s: dict) -> str:
    icon = "🟢" if s["side"] == "BUY" else "🔴"
    return (
        f"{icon} {s['side']} XAUUSD ({INTERVAL})\n"
        f"เข้า: {s['entry']:.2f}\n"
        f"SL: {s['sl']:.2f}\n"
        f"TP: {s['tp']:.2f}  (RR 1:{RR:g})\n"
        f"RSI: {s['rsi']:.1f}\n"
        f"แท่งเวลา: {s['time']}\n"
        f"⚠️ ไม่ใช่คำแนะนำการลงทุน ควรคุมความเสี่ยงต่อไม้ไม่เกิน 1-2%"
    )

async def analyze():
    df = await asyncio.to_thread(fetch)
    df = add_indicators(df)
    return df, get_signal(df)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "บอทสัญญาณทอง XAUUSD ระยะสั้น\n"
        "/signal - เช็คสัญญาณตอนนี้\n"
        "/status - ดูเทรนด์และค่าอินดิเคเตอร์\n"
        "/auto_on - เปิดแจ้งเตือนอัตโนมัติ\n"
        "/auto_off - ปิดแจ้งเตือน"
    )

async def signal_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, sig = await analyze()
    await update.message.reply_text(
        format_signal(sig) if sig else "ยังไม่มีสัญญาณเข้าที่เข้าเงื่อนไข รอก่อน ⏳"
    )

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    df, _ = await analyze()
    r = df.iloc[-2]
    trend = "ขาขึ้น 📈" if r["Close"] > r["ema50"] else "ขาลง 📉"
    await update.message.reply_text(
        f"ราคา: {r['Close']:.2f}\nเทรนด์ (เทียบ EMA50): {trend}\n"
        f"EMA9: {r['ema9']:.2f} | EMA21: {r['ema21']:.2f}\n"
        f"RSI: {r['rsi']:.1f} | ATR: {r['atr']:.2f}"
    )

async def auto_job(ctx: ContextTypes.DEFAULT_TYPE):
    _, sig = await analyze()
    if not sig or ctx.bot_data.get("last_sig") == sig["time"]:
        return
    ctx.bot_data["last_sig"] = sig["time"]
    for chat_id in ctx.bot_data.get("chats", set()):
        await ctx.bot.send_message(chat_id, format_signal(sig))

async def auto_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.bot_data.setdefault("chats", set()).add(update.effective_chat.id)
    await update.message.reply_text("เปิดแจ้งเตือนอัตโนมัติแล้ว ✅")

async def auto_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.bot_data.setdefault("chats", set()).discard(update.effective_chat.id)
    await update.message.reply_text("ปิดแจ้งเตือนแล้ว")

def main():
    if not TOKEN:
        raise SystemExit("ตั้งค่า TELEGRAM_TOKEN ก่อน")
    
    t = threading.Thread(target=run_web_server, daemon=True)
    t.start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("auto_on", auto_on))
    app.add_handler(CommandHandler("auto_off", auto_off))
    app.job_queue.run_repeating(auto_job, interval=CHECK_EVERY, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
