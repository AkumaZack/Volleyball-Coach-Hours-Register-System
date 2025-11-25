from flask import Flask, request, render_template, redirect
import sqlite3
from datetime import datetime, timedelta
import requests
import os

app = Flask(__name__)

# 讀取環境變數（在 Render 設定 Environment Variables）
ADMIN_KEY = os.environ.get("ADMIN_KEY", "default_admin_key")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 取得台灣時間（UTC+8）
def get_tw_time():
    return datetime.utcnow() + timedelta(hours=8)

# 初始化資料庫
def init_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            school TEXT,
            phone TEXT,
            certificate TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Telegram 通知功能
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }
        requests.post(url, data=payload)
    except Exception as e:
        print("Telegram Error:", e)

# 前台首頁（教練填基本資料）
@app.route("/")
def index():
    return render_template("main.html")

# 第二頁：基本資料送出後 → 填教練證
@app.route("/basic", methods=["POST"])
def basic():
    name = request.form["name"]
    school = request.form["school"]
    phone = request.form["phone"]

    # 存進 session-like 暫存方式（不使用 session 避免 Render 問題）
    global temp_info
    temp_info = {"name": name, "school": school, "phone": phone}

    return render_template("certificates.html", info=temp_info)

# 教練證送出
@app.route("/certificates", methods=["POST"])
def certificates():
    global temp_info
    cert = request.form["certificate"]

    # 取得台灣時間
    now = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")

    # 寫入資料庫
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO submissions (name, school, phone, certificate, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (temp_info["name"], temp_info["school"], temp_info["phone"], cert, now))
    conn.commit()
    conn.close()

    # Telegram 通知
    msg = (
        f"🏐 教練證資料已送出\n"
        f"填寫人：{temp_info['name']}\n"
        f"學校：{temp_info['school']}\n"
        f"電話：{temp_info['phone']}\n"
        f"\n教練與證號：\n- {temp_info['name']}：{cert}\n"
        f"\n送出時間： {now}"
    )
    send_telegram(msg)

    return render_template("done.html")

# 後台統計
@app.route("/admin")
def admin():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return "Unauthorized"

    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT name, school, phone, certificate, created_at FROM submissions ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    return render_template("admin.html", rows=rows)

# Render 部署需要
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
