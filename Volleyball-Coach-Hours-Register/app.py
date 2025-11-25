import os
import sqlite3
from datetime import datetime, timedelta

import requests
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g, abort
)

# 嘗試載入本機 config.py（本機測試用，可有可無）
try:
    import config
except ImportError:
    class config:
        ADMIN_KEY = "changeme"
        FLASK_SECRET_KEY = "a-secret-key"


app = Flask(__name__)
app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    getattr(config, "FLASK_SECRET_KEY", "a-secret-key")
)

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


# ------------------ 共用：台灣時間 ------------------ #

def get_tw_now() -> datetime:
    """取得台灣時間（UTC+8）"""
    return datetime.utcnow() + timedelta(hours=8)


# ------------------ 資料庫相關 ------------------ #

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            school TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            coach_name TEXT NOT NULL,
            coach_license TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id)
        )
        """
    )

    db.commit()


# 啟動時自動建表
with app.app_context():
    init_db()


# ------------------ Telegram 通知 ------------------ #

def send_telegram_notify(text: str):
    """
    使用 Telegram Bot 發送通知。
    - TELEGRAM_BOT_TOKEN
    - TELEGRAM_CHAT_ID
    兩個環境變數沒設定就只印在 log，不會讓系統炸掉。
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("【Telegram 未設定完整】不發送通知。訊息內容：")
        print(text)
        print("==========")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
    }

    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code != 200:
            print("Telegram 通知失敗，狀態碼：", resp.status_code)
            print("回應內容：", resp.text)
        else:
            print("Telegram 通知已送出。")
    except Exception as e:
        print("Telegram 通知發送錯誤：", e)


# ------------------ 前台流程 ------------------ #


@app.route("/")
def index():
    # 首頁直接導向基本資料頁（對應 basic_info.html）
    return redirect(url_for("basic_info"))


@app.route("/basic", methods=["GET", "POST"])
def basic_info():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        school = request.form.get("school", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not school or not phone:
            error = "請完整填寫基本資料。"
            return render_template("basic_info.html", error=error, form=request.form)

        # 把基本資料暫存到 session，第二頁會用到
        session["basic_info"] = {
            "name": name,
            "school": school,
            "phone": phone,
        }
        return redirect(url_for("certificates"))

    return render_template("basic_info.html", error=None, form={})


@app.route("/certificates", methods=["GET", "POST"])
def certificates():
    basic_info = session.get("basic_info")
    if not basic_info:
        # 如果沒有基本資料，導回第一頁
        return redirect(url_for("basic_info"))

    if request.method == "POST":
        coach_names = request.form.getlist("coach_name")
        coach_licenses = request.form.getlist("coach_license")

        pairs = []
        for n, c in zip(coach_names, coach_licenses):
            n = n.strip()
            c = c.strip()
            if n and c:
                pairs.append((n, c))

        if not pairs:
            error = "請至少填寫一筆教練姓名與教練證號。"
            return render_template("certificates.html", error=error, basic=basic_info)

        db = get_db()
        now_dt = get_tw_now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # 寫入 submissions
        cur = db.execute(
            """
            INSERT INTO submissions (name, school, phone, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (basic_info["name"], basic_info["school"], basic_info["phone"], now_str),
        )
        submission_id = cur.lastrowid

        # 寫入多筆 certificates
        db.executemany(
            """
            INSERT INTO certificates (submission_id, coach_name, coach_license)
            VALUES (?, ?, ?)
            """,
            [(submission_id, n, c) for n, c in pairs],
        )
        db.commit()

        # 組 Telegram 訊息（用台灣時間）
        lines = [
            "🏐 教練證資料已送出",
            f"填寫人：{basic_info['name']}",
            f"學校：{basic_info['school']}",
            f"電話：{basic_info['phone']}",
            "",
            "教練與證號：",
        ]
        for n, c in pairs:
            lines.append(f"- {n}：{c}")
        lines.append("")
        lines.append(f"送出時間： {now_str}")

        body = "\n".join(lines)
        send_telegram_notify(body)

        # 用完就清掉 basic_info
        session.pop("basic_info", None)

        return render_template("complete.html")

    # GET：顯
