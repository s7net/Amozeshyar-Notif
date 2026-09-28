#!/bin/bash

# ==============================================================================
# Amoozeshyar-Notif Watchdog & Keep-Alive Script
# Suitable for Cron Jobs (e.g. cPanel / Linux VPS) to ensure the bot stays alive.
# Usage:
#   ./watchdog.sh          # Default watchdog check (starts if down, exits if running)
#   ./watchdog.sh start    # Explicit start
#   ./watchdog.sh stop     # Gracefully stop the bot
#   ./watchdog.sh restart  # Restart the bot
#   ./watchdog.sh status   # Check running status
# ==============================================================================

# 1. Automatically detect application directory
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR" || exit 1

LOCK_FILE="$APP_DIR/lock.file"
LOG_FILE="$APP_DIR/bot.log"
PYTHON=""

# Ensure Python unbuffered output so logs write immediately to bot.log
export PYTHONUNBUFFERED=1

# 2. Automatically detect Python executable in virtual environment
if [ -f "$APP_DIR/.venv/bin/python" ]; then
    PYTHON="$APP_DIR/.venv/bin/python"
elif [ -d "$HOME/virtualenv" ]; then
    # Look for virtualenv created by cPanel Python Selector
    # e.g., /home/username/virtualenv/relative_project_path/*/bin/python
    REL_PATH="${APP_DIR#$HOME/}"
    if [ -n "$REL_PATH" ] && [ "$REL_PATH" != "$APP_DIR" ]; then
        # Find first matching virtualenv python
        VENV_PY=$(find "$HOME/virtualenv/$REL_PATH" -maxdepth 3 -path "*/bin/python" -type f 2>/dev/null | head -n 1)
        if [ -n "$VENV_PY" ]; then
            PYTHON="$VENV_PY"
        fi
    fi
fi

# Fallback to system python if no virtualenv python is found
if [ -z "$PYTHON" ]; then
    PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null)
fi

if [ -z "$PYTHON" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Error: Python executable not found!" >> "$LOG_FILE"
    exit 1
fi

is_running() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

start_bot() {
    nohup "$PYTHON" main.py >> "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$LOCK_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') Bot started with PID $PID using Python: $PYTHON" >> "$LOG_FILE"
}

stop_bot() {
    if [ -f "$LOCK_FILE" ]; then
        PID=$(cat "$LOCK_FILE")
        if is_running "$PID"; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') Stopping bot (PID $PID)..." >> "$LOG_FILE"
            kill "$PID" 2>/dev/null
            # Wait up to 5 seconds for termination
            for _ in {1..5}; do
                if ! is_running "$PID"; then
                    break
                fi
                sleep 1
            done
            if is_running "$PID"; then
                kill -9 "$PID" 2>/dev/null
            fi
            echo "$(date '+%Y-%m-%d %H:%M:%S') Bot stopped." >> "$LOG_FILE"
        fi
        rm -f "$LOCK_FILE"
    else
        echo "No lock file found. Bot may not be running."
    fi
}

status_bot() {
    if [ -f "$LOCK_FILE" ]; then
        PID=$(cat "$LOCK_FILE")
        if is_running "$PID"; then
            echo "Bot is RUNNING (PID: $PID)"
            return 0
        else
            echo "Bot is NOT running (stale lock file found for PID: $PID)"
            return 1
        fi
    else
        echo "Bot is NOT running"
        return 1
    fi
}

ACTION="${1:-check}"

case "$ACTION" in
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 1
        start_bot
        ;;
    status)
        status_bot
        ;;
    start)
        if [ -f "$LOCK_FILE" ]; then
            PID=$(cat "$LOCK_FILE")
            if is_running "$PID"; then
                echo "Bot is already running (PID: $PID)"
                exit 0
            else
                echo "$(date '+%Y-%m-%d %H:%M:%S') Stale lock detected for PID $PID" >> "$LOG_FILE"
                rm -f "$LOCK_FILE"
                start_bot
            fi
        else
            start_bot
        fi
        ;;
    check|*)
        # Default keep-alive check (used by Cron)
        if [ -f "$LOCK_FILE" ]; then
            PID=$(cat "$LOCK_FILE")
            if is_running "$PID"; then
                # Already healthy and running
                exit 0
            else
                echo "$(date '+%Y-%m-%d %H:%M:%S') Stale lock detected for PID $PID (process died). Restarting..." >> "$LOG_FILE"
                rm -f "$LOCK_FILE"
                start_bot
            fi
        else
            start_bot
        fi
        ;;
esac
