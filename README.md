# Amoozeshyar iGap to Telegram Forwarder 🎓🚀

This project allows you to capture messages, announcements, and grade notifications from the **Amoozeshyar** bot in iGap (`@amoozeshbot`) in real time and automatically forward them directly to your **Telegram** chat or channel.

---

## 🛠 Prerequisites

- **Python:** Version 3.12 or higher
- **Package Manager:** [uv](https://docs.astral.sh/uv/)

---

## ⚡️ Quick Installation with uv

### 1. Install Dependencies
Run the following command inside the project directory:
```bash
uv sync
```

### 2. Configure Telegram Credentials
Edit the `.env` file and set your Telegram Bot token and Chat ID:
```env
# Bot token received from @BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ

# Your numeric Telegram user ID or channel ID (e.g. from @userinfobot)
TELEGRAM_CHAT_ID=123456789
```

---

## 🔑 Step 1: Login & Save iGap Session

Authenticate your iGap account using `login.py`:
```bash
uv run python login.py
```

Follow the prompts:
1. Enter your Iranian mobile phone number (e.g., `09123456789`).
2. Enter the 5-digit verification OTP code received via SMS or inside the iGap app.
3. Upon successful verification, session credentials will be saved in `session.json`.

---

## 🤖 Step 2: Start the Daemon Forwarder

Once authenticated, start the continuous forwarder service:
```bash
uv run python main.py
```

The service will:
- Connect securely to iGap's WebSocket endpoint.
- Authenticate using your saved session token.
- Send periodic keepalive heartbeat packets.
- Resolve and monitor `@amoozeshbot`.
- Forward any incoming Amoozeshyar messages immediately to Telegram.
- Automatically reconnect with exponential backoff if the network drops.

---

## 📁 Project Structure

```text
├── igap_proto/           # Compiled Python protobuf classes for iGap API
├── config.py             # Global configuration, endpoints, action IDs
├── igap_client.py        # Async iGap client with RSA handshake & AES encryption
├── telegram_sender.py    # Telegram Bot API client and message formatter
├── login.py              # Interactive authentication CLI
├── main.py               # Long-running daemon listener and forwarder
├── pyproject.toml        # Dependencies managed with uv
├── .env.example          # Environment variables template
└── README.md             # Documentation
```
