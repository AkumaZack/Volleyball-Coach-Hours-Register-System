import os
import sqlite3
from datetime import datetime

import requests  # 用來呼叫 Telegram API

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g, abort
)

# 嘗試載入本機 config.py（本機測試可用，不強制）
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

# SQLite 資料庫位置
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


# ------------------ 資料庫相關 ------------------ #

def get_db():
    """取得目前 request 使用的資料庫連線"""
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
    """建立所需的資料表（若不存在）"""
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            school TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            coach_name TEXT NOT NULL,
            coach_license TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id)
        )
    """)

    db.commit()


# ✔ 關鍵：不管在本機還是 Render，啟動時自動建立資料表
with app.app_context():
    init_db()


# ------------------ Telegram 通知 ------------------ #

def send_telegram_notify(text: str):
    """
    使用 Telegram Bot 發送通知到手機。
    - TELEGRAM_BOT_TOKEN：Bot Token
    - TELEGRAM_CHAT_ID：你自己的 chat_id
    任何錯誤只會印在 log，不會影響網站運作。
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("【Telegram 未設定完整】不發送通知。")
        print("訊息內容：")
        print(text)
        print("==========")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text
    }

    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code != 200:
            print("Telegram 通知失敗，狀態碼：", resp.status_code)
            print("回應內容：", resp.text)
        else:
            print("Telegram 通知已送出。")
    except Exception as e:
        print("Telegram 通知發送時發生錯誤：", e)
        return


# ------------------ 路由 ------------------ #

@app.route("/")
def index():
    return redirect(url_for("basic_info"))


# 第一頁：基本資料
@app.route("/basic", methods=["GET", "POST"])
def basic_info():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        school = request.form.get("school", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not school or not phone:
            error = "請填寫完整基本資料。"
            return render_template("basic_info.html", error=error, form=request.form)

        session["basic_info"] = {
            "name": name,
            "school": school,
            "phone": phone,
        }
        return redirect(url_for("certificates"))

    return render_template("basic_info.html", error=None, form={})


# 第二頁：多筆教練證號
@app.route("/certificates", methods=["GET", "POST"])
def certificates():
    basic_info = session.get("basic_info")
    if not basic_info:
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
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = db.execute(
            "INSERT INTO submissions (name, school, phone, created_at) VALUES (?, ?, ?, ?)",
            (basic_info["name"], basic_info["school"], basic_info["phone"], now),
        )
        submission_id = cur.lastrowid

        db.executemany(
            "INSERT INTO certificates (submission_id, coach_name, coach_license) VALUES (?, ?, ?)",
            [(submission_id, n, c) for n, c in pairs],
        )
        db.commit()

        # 組成要傳到 Telegram 的文字
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
        lines.append(f"送出時間：{now}")
        body = "\n".join(lines)

        # 發送 Telegram 通知（失敗也不會影響流程）
        send_telegram_notify(body)

        # 清除 session，避免重送
        session.pop("basic_info", None)

        return render_template("complete.html")

    return render_template("certificates.html", error=None, basic=basic_info)


# 後台頁面
@app.route("/admin")
def admin():
    admin_key = os.getenv("ADMIN_KEY", getattr(config, "ADMIN_KEY", "changeme"))
    key = request.args.get("key", "")
    if key != admin_key:
        return abort(403)

    db = get_db()
    submissions = db.execute(
        """
        SELECT s.id,
               s.name,
               s.school,
               s.phone,
               s.created_at,
               COUNT(c.id) AS coach_count
        FROM submissions s
        LEFT JOIN certificates c ON c.submission_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        """
    ).fetchall()

    total_submissions = len(submissions)
    total_certificates = db.execute(
        "SELECT COUNT(*) FROM certificates"
    ).fetchone()[0]

    details = {}
    rows = db.execute(
        """
        SELECT s.id AS submission_id,
               c.coach_name,
               c.coach_license
        FROM submissions s
        JOIN certificates c ON c.submission_id = s.id
        ORDER BY s.id, c.id
        """
    ).fetchall()
    for row in rows:
        sid = row["submission_id"]
        details.setdefault(sid, []).append(row)

    return render_template(
        "admin.html",
        submissions=submissions,
        details=details,
        total_submissions=total_submissions,
        total_certificates=total_certificates,
    )


# CLI：本機可以用 "flask init-db" 來初始化
@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Initialized the database.")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
