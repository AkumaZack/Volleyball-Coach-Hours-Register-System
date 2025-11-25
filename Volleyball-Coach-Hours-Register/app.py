import os
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g, abort
)

# 嘗試載入本機 config.py（本機測試使用）
try:
    import config
except ImportError:
    class config:
        ADMIN_KEY = "changeme"
        EMAIL_SMTP_SERVER = "smtp.gmail.com"
        EMAIL_SMTP_PORT = 587
        EMAIL_USERNAME = ""
        EMAIL_PASSWORD = ""
        EMAIL_TO = ""
        FLASK_SECRET_KEY = "a-secret-key"


app = Flask(__name__)
app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    getattr(config, "FLASK_SECRET_KEY", "a-secret-key")
)

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


# ------------------ 資料庫 ------------------ #

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


# ✔ 關鍵：Render 啟動時自動建立資料表
with app.app_context():
    init_db()


# ------------------ EMAIL ------------------ #

def send_email_notify(subject, body):
    """
    Email 寄不出去也不會讓系統 500。
    """

    username = os.getenv("EMAIL_USERNAME", getattr(config, "EMAIL_USERNAME", ""))
    password = os.getenv("EMAIL_PASSWORD", getattr(config, "EMAIL_PASSWORD", ""))
    to_addr = os.getenv("EMAIL_TO", getattr(config, "EMAIL_TO", ""))
    smtp_server = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("EMAIL_SMTP_PORT", 587))

    if not username or not password or not to_addr:
        print("【Email 未設定完整】")
        print(body)
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = username
        msg["To"] = to_addr

        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

        print("Email 通知已寄出")

    except Exception as e:
        print("Email 寄送失敗：", e)
        return


# ------------------ ROUTES ------------------ #

@app.route("/")
def index():
    return redirect(url_for("basic_info"))


@app.route("/basic", methods=["GET", "POST"])
def basic_info():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        school = request.form.get("school", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not school or not phone:
            return render_template("basic_info.html", error="請完整填寫基本資料", form=request.form)

        session["basic_info"] = {
            "name": name,
            "school": school,
            "phone": phone
        }
        return redirect(url_for("certificates"))

    return render_template("basic_info.html", form={}, error=None)


@app.route("/certificates", methods=["GET", "POST"])
def certificates():
    basic_info = session.get("basic_info")
    if not basic_info:
        return redirect(url_for("basic_info"))

    if request.method == "POST":
        names = request.form.getlist("coach_name")
        licenses = request.form.getlist("coach_license")

        pairs = [(n.strip(), l.strip()) for n, l in zip(names, licenses) if n.strip() and l.strip()]

        if not pairs:
            return render_template("certificates.html", basic=basic_info, error="請至少新增 1 筆")

        db = get_db()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = db.execute("""
            INSERT INTO submissions (name, school, phone, created_at)
            VALUES (?, ?, ?, ?)
        """, (basic_info["name"], basic_info["school"], basic_info["phone"], now))

        sid = cur.lastrowid

        db.executemany("""
            INSERT INTO certificates (submission_id, coach_name, coach_license)
            VALUES (?, ?, ?)
        """, [(sid, n, c) for n, c in pairs])

        db.commit()

        # 組 Email
        body = f"""
🏐 教練證資料已送出

填寫人：{basic_info['name']}
學校：{basic_info['school']}
電話：{basic_info['phone']}

教練證資料如下：
""" + "\n".join([f"- {n}：{c}" for n, c in pairs]) + f"""

送出時間：{now}
"""

        # Email 不會讓系統 500
        send_email_notify("教練證資料已送出", body)

        session.pop("basic_info", None)
        return render_template("complete.html")

    return render_template("certificates.html", basic=basic_info, error=None)


# ------------------ Admin ------------------ #

@app.route("/admin")
def admin():
    admin_key = os.getenv("ADMIN_KEY", getattr(config, "ADMIN_KEY", "changeme"))
    key = request.args.get("key", "")

    if key != admin_key:
        return abort(403)

    db = get_db()

    submissions = db.execute("""
        SELECT s.id, s.name, s.school, s.phone, s.created_at,
               COUNT(c.id) AS count
        FROM submissions s
        LEFT JOIN certificates c ON s.id = c.submission_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """).fetchall()

    details = {}
    rows = db.execute("""
        SELECT submission_id, coach_name, coach_license
        FROM certificates
        ORDER BY submission_id, id
    """).fetchall()

    for r in rows:
        details.setdefault(r["submission_id"], []).append(r)

    return render_template(
        "admin.html",
        submissions=submissions,
        details=details,
        total_submissions=len(submissions),
        total_certificates=len(rows)
    )


# ------------------ CLI ------------------ #

@app.cli.command("init-db")
def init_db_cmd():
    init_db()
    print("資料庫已初始化")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
