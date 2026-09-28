import html
import logging
from typing import Optional
import httpx
import jdatetime

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("telegram_sender")


class TelegramSender:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @staticmethod
    def format_amoozeshyar_message(
        content: str,
        sender_username: str = "amoozeshbot",
        attachment_name: Optional[str] = None,
        attachment_url: Optional[str] = None,
    ) -> str:
        """Format incoming Amoozeshyar iGap message for Telegram."""
        now = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M:%S")
        escaped_content = html.escape(content.strip()) if content else ""

        blocks = []
        if escaped_content:
            blocks.append(escaped_content)
        elif not attachment_name:
            blocks.append("<i>[پیام بدون متن]</i>")

        if attachment_name:
            escaped_att = html.escape(attachment_name)
            if attachment_url:
                blocks.append(f"📎 <b>پیوست:</b> <a href=\"{attachment_url}\">{escaped_att}</a>")
            else:
                blocks.append(f"📎 <b>پیوست:</b> {escaped_att}")

        footer_elements = [f"🗓 <code>{now}</code>"]
        if sender_username:
            footer_elements.append(f"@{sender_username}")

        blocks.append(" | ".join(footer_elements))

        return "\n\n".join(blocks)

    async def send_text(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send message text to Telegram, splitting long messages if necessary."""
        if not self.is_configured():
            logger.warning("Telegram bot credentials (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID) are not configured.")
            return False

        max_chunk = 4000
        chunks = [text[i:i + max_chunk] for i in range(0, len(text), max_chunk)]

        async with httpx.AsyncClient(timeout=15.0) as client:
            success = True
            for chunk in chunks:
                payload = {
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                try:
                    resp = await client.post(self.api_url, json=payload)
                    res_json = resp.json()
                    if resp.status_code == 200 and res_json.get("ok"):
                        logger.info("Message successfully delivered to Telegram.")
                    else:
                        logger.error(f"Failed to send message to Telegram: {resp.text}")
                        # Fallback to plain text if HTML parsing failed
                        if "can't parse entities" in resp.text:
                            payload.pop("parse_mode")
                            retry_resp = await client.post(self.api_url, json=payload)
                            if retry_resp.status_code == 200:
                                logger.info("Message delivered to Telegram as plain text.")
                            else:
                                success = False
                        else:
                            success = False
                except Exception as e:
                    logger.error(f"Network error while connecting to Telegram API: {e}")
                    success = False

            return success

    async def forward_amoozeshyar_message(
        self,
        content: str,
        sender_username: str = "amoozeshbot",
        attachment_name: Optional[str] = None,
        attachment_url: Optional[str] = None,
    ) -> bool:
        """Format and forward Amoozeshyar message to Telegram."""
        formatted = self.format_amoozeshyar_message(
            content=content,
            sender_username=sender_username,
            attachment_name=attachment_name,
            attachment_url=attachment_url,
        )
        return await self.send_text(formatted, parse_mode="HTML")
