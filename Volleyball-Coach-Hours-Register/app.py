import os
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g, abort
)

# 嘗試載入本機 config（在雲端可省略，改用環境變數）
try:
    import config  # type: ignore
except ImportError:
    class config:  # type: ignore
        ADMIN_KEY = "changeme"
        EMAIL_SMTP_SERVER = "smtp.gmail.com"
        EMAIL_SMTP_PORT = 587
        EMAIL_USERNAME = ""
        EMAIL_PASSWORD = ""
        EMAIL_TO = ""


class Settings:
    """設定來源：
    1. 先讀環境變數（雲端部署用）
    2. 若沒有，退回本機 config.py (開發用)
    """
    ADMIN_KEY = os.getenv("ADMIN_KEY", getattr(config, "ADMIN_KEY", "changeme"))

    EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", getattr(config, "EMAIL_SMTP_SERVER", "smtp.gmail.com"))
    EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", str(getattr(config, "EMAIL_SMTP_PORT", 587))))
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", getattr(config, "EMAIL_USERNAME", ""))
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", getattr(config, "EMAIL_PASSWORD", ""))
    EMAIL_TO = os.getenv("EMAIL_TO", getattr(config, "EMAIL_TO", ""))


settings = Settings()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "a-very-secret-key-change-this")

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


# ------------------ 資料庫相關 ------------------ #

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    # submissions: 基本資料
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
    # certificates: 多筆教練證
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            coach_name TEXT NOT NULL,
            coach_license TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
        )
        """
    )
    db.commit()


# ------------------ Email 通知 ------------------ #

def send_email_notify(subject: str, body: str):
    """用 Gmail 寄通知給你自己"""
    username = settings.EMAIL_USERNAME
    password = settings.EMAIL_PASSWORD
    to_addr = settings.EMAIL_TO
    smtp_server = settings.EMAIL_SMTP_SERVER
    smtp_port = settings.EMAIL_SMTP_PORT

    if not username or not password or not to_addr:
        print("【提醒】Email 尚未完整設定，訊息內容如下：")
        print("Subject:", subject)
        print(body)
        print("========== 結束 ==========")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        print("Email 通知已寄出。")
    except Exception as e:
        print("Email 通知失敗：", e)
        print("原始訊息：")
        print(body)


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

        # 存進 session，待會第二頁用
        session["basic_info"] = {
            "name": name,
            "school": school,
            "phone": phone,
        }
        return redirect(url_for("certificates"))

    # GET
    return render_template("basic_info.html", error=None, form={})


# 第二頁：多筆教練證號
@app.route("/certificates", methods=["GET", "POST"])
def certificates():
    basic_info = session.get("basic_info")
    if not basic_info:
        # 沒有基本資料就導回第一頁
        return redirect(url_for("basic_info"))

    if request.method == "POST":
        coach_names = request.form.getlist("coach_name")
        coach_licenses = request.form.getlist("coach_license")

        # 過濾掉空白的
        pairs = []
        for n, c in zip(coach_names, coach_licenses):
            n = n.strip()
            c = c.strip()
            if n and c:
                pairs.append((n, c))

        if not pairs:
            error = "請至少填寫一筆教練姓名與教練證號。"
            return render_template("certificates.html", error=error, basic=basic_info)

        # 存進資料庫
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

        # 組 Email 內容
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

        # 寄 Email 通知
        send_email_notify("教練證資料已送出", body)

        # 清掉 session
        session.pop("basic_info", None)

        return render_template("complete.html")

    # GET
    return render_template("certificates.html", error=None, basic=basic_info)


# 後台頁面（簡單密碼驗證）
@app.route("/admin")
def admin():
    key = request.args.get("key", "")
    if key != settings.ADMIN_KEY:
        return abort(403)

    db = get_db()
    # 整理出每筆 submission + 統計
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

    # 明細：每筆 submission 底下的所有教練
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
        key=key,
        submissions=submissions,
        details=details,
        total_submissions=total_submissions,
        total_certificates=total_certificates,
    )


# 初始化 DB（第一次啟動用）
@app.cli.command("init-db")
def init_db_command():
    """flask init-db 用"""
    init_db()
    print("Initialized the database.")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    # 本機開發用
    app.run(debug=True, host="0.0.0.0", port=5000)
