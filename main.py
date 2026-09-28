import asyncio
import logging
import signal
import sys
from typing import Any, Optional

from config import (
    AMOOZESH_BOT_USERNAME,
    AMOOZESH_BOT_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    load_session,
)
from igap_client import IGapClient, IGapError
from telegram_sender import TelegramSender

# Configure logger format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


class AmoozeshyarForwarder:
    def __init__(self):
        self.telegram = TelegramSender()
        self.client: Optional[IGapClient] = None
        self.target_user_id: Optional[int] = None
        if AMOOZESH_BOT_ID:
            try:
                self.target_user_id = int(AMOOZESH_BOT_ID)
                logger.info(f"Target Bot ID loaded from .env: {self.target_user_id}")
            except ValueError:
                logger.warning(f"Invalid AMOOZESH_BOT_ID in .env: {AMOOZESH_BOT_ID}")
        self.target_room_id: Optional[int] = None
        self.target_username = AMOOZESH_BOT_USERNAME.lower()
        self.is_running = True

    async def _resolve_amoozeshyar_target(self, client: IGapClient) -> None:
        """Query user and room IDs of Amoozeshyar bot for exact message filtering."""
        try:
            logger.info(f"Resolving bot username @{self.target_username} in iGap...")
            res = await client.resolve_username(self.target_username)
            if res.user and res.user.id:
                self.target_user_id = res.user.id
                logger.info(f"Target Bot User ID: {self.target_user_id}")
            if res.room and res.room.id:
                self.target_room_id = res.room.id
                logger.info(f"Target Bot Chat Room ID: {self.target_room_id}")
        except Exception as e:
            logger.warning(
                f"Could not resolve username @{self.target_username} yet: {e}"
            )

    async def _on_incoming_message(self, action_id: int, msg_response: Any) -> None:
        """Handle incoming messages from iGap server."""
        room_id = getattr(msg_response, "room_id", None)
        room_message = getattr(msg_response, "room_message", None)

        if not room_message:
            return

        author_user_id = None
        if hasattr(room_message, "author") and hasattr(room_message.author, "user"):
            author_user_id = room_message.author.user.user_id

        # Check if message originates from Amoozeshyar bot
        is_from_amoozeshyar = False

        if self.target_room_id and room_id == self.target_room_id:
            is_from_amoozeshyar = True
        elif self.target_user_id and author_user_id == self.target_user_id:
            is_from_amoozeshyar = True
        elif not self.target_room_id and not self.target_user_id:
            logger.info(f"Incoming message with unconfirmed filter - Room: {room_id}, Author: {author_user_id}")
            is_from_amoozeshyar = True

        if not is_from_amoozeshyar:
            logger.debug(f"Message from other room ({room_id}) ignored.")
            return

        text = (room_message.message or "").strip()
        if not text:
            logger.debug("Received empty message text; ignored.")
            return

        logger.info("=" * 50)
        logger.info("📩 New message received from Amoozeshyar bot!")
        logger.info(f"Content:\n{text}")
        logger.info("=" * 50)

        # Forward to Telegram
        if self.telegram.is_configured():
            logger.info("Forwarding message to Telegram...")
            sent = await self.telegram.forward_amoozeshyar_message(
                content=text,
                sender_username=self.target_username,
            )
            if sent:
                logger.info("✅ Message forwarded to Telegram successfully.")
            else:
                logger.error("❌ Failed to forward message to Telegram.")
        else:
            logger.warning("Telegram credentials not configured in .env; message logged only in console.")

    async def start(self) -> None:
        """Main service loop with automatic reconnection (Exponential Backoff)."""
        session = load_session()
        token = session.get("token")

        if not token:
            print("\n" + "=" * 60)
            print("⚠️ You are not logged in to iGap yet!")
            print("👉 Please run the login script first to authenticate:")
            print("   uv run python login.py")
            print("=" * 60 + "\n")
            sys.exit(1)

        if not self.telegram.is_configured():
            logger.warning("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are not set in .env file.")
            logger.warning("Messages will only be printed to the terminal until .env is configured.")

        reconnect_delay = 5

        while self.is_running:
            client = IGapClient()
            self.client = client
            try:
                logger.info("Connecting to iGap...")
                await client.connect()

                logger.info("Authenticating with saved token...")
                await client.login(token)
                logger.info("✅ Successfully logged in to iGap account!")

                # Resolve Amoozeshyar bot identifiers
                await self._resolve_amoozeshyar_target(client)

                # Register message listener
                client.on_message(self._on_incoming_message)
                logger.info(f"👂 Listening for messages from @{self.target_username}...")

                reconnect_delay = 5

                # Keep alive while connection remains active
                while client.is_connected and self.is_running:
                    await asyncio.sleep(1)

            except IGapError as e:
                logger.error(f"iGap protocol error: {e}")
                if e.major_code == 109:  # Invalid / expired session token
                    logger.critical("Session token is invalid or expired. Please run login.py again.")
                    break
            except Exception as e:
                logger.error(f"Connection error: {e}")
            finally:
                await client.close()

            if self.is_running:
                logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def stop(self) -> None:
        self.is_running = False
        if self.client:
            await self.client.close()


def main():
    forwarder = AmoozeshyarForwarder()

    def signal_handler(*_):
        logger.info("Shutdown signal received. Stopping forwarder...")
        asyncio.create_task(forwarder.stop())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(forwarder.start())
    except KeyboardInterrupt:
        logger.info("Application terminated cleanly.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
