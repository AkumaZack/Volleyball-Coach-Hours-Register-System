# Volleyball-Coach-Hours-Register

中華民國排球協會教練時數登記系統（Flask）。

## 本機開發

```bash
python -m venv venv
venv\Scripts\activate  # Windows
# 或 source venv/bin/activate  # macOS / Linux

pip install -r requirements.txt
flask --app app.py init-db
python app.py
```

開啟瀏覽器：`http://127.0.0.1:5000/basic`

## 環境變數設定（本機 .env 或雲端）

- `ADMIN_KEY`：後台密碼，對應 `/admin?key=XXXX`
- `FLASK_SECRET_KEY`：Flask session 用隨機字串
- `EMAIL_SMTP_SERVER`：SMTP 主機（Gmail 為 `smtp.gmail.com`）
- `EMAIL_SMTP_PORT`：SMTP 連接埠（Gmail 為 `587`）
- `EMAIL_USERNAME`：用來寄信的帳號（通常是 Gmail）
- `EMAIL_PASSWORD`：對應帳號的「應用程式密碼」
- `EMAIL_TO`：要接收通知的 Email

雲端（例如 Render）請在 Dashboard 的 Environment 介面設定上述變數。
本機開發也可以建立 `config.py`，內容可參考 `config_example.py`。
