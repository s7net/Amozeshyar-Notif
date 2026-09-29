import html
import logging
import re
from typing import Any, Dict, Optional
import httpx

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
    def extract_otp_code(text: str) -> Optional[str]:
        """Extract OTP / login code from Amoozeshyar message."""
        if not text:
            return None

        # Convert Persian / Arabic digits to standard ASCII digits
        persian_to_eng = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        norm_text = text.translate(persian_to_eng)

        # 1. Match 'رمز ورود', 'کد ورود', 'کد تایید', 'رمز یکبار مصرف', etc.
        match = re.search(
            r"(?:رمز\s*(?:ورود|یکبار\s*مصرف|موقت)|کد\s*(?:ورود|تایید|تأیید|فعال[\s‌]*سازی))(?:\s+شما)?[\s:]+([0-9]{4,8})",
            norm_text,
        )
        if match:
            return match.group(1)

        # 2. Fallback: match standalone 5-6 digit code if mentions Amoozeshyar
        if "آموزشیار" in norm_text:
            fallback = re.search(r"(?<![:\d])(\d{5,6})(?![:\d])", norm_text)
            if fallback:
                return fallback.group(1)

        return None

    @classmethod
    def format_amoozeshyar_message(
        cls,
        content: str,
        code: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Format incoming Amoozeshyar text message for Telegram (pure message content only)."""
        escaped_content = html.escape(content.strip()) if content else ""

        if not escaped_content:
            return "<i>[پیام بدون متن]</i>"

        # Highlight code inside message text if detected so it can be tapped directly
        if code:
            digits_map = {
                "0": "[0۰٠]", "1": "[1۱١]", "2": "[2۲٢]", "3": "[3۳٣]", "4": "[4۴٤]",
                "5": "[5۵٥]", "6": "[6۶٦]", "7": "[7۷٧]", "8": "[8٨]", "9": "[9۹٩]",
            }
            pattern = "".join(digits_map.get(d, d) for d in code)
            escaped_content = re.sub(
                rf"((?:رمز\s*(?:ورود|یکبار\s*مصرف|موقت)|کد\s*(?:ورود|تایید|تأیید|فعال[\s‌]*سازی))(?:\s+شما)?[\s:]+)({pattern})",
                r"\1<code>\2</code>",
                escaped_content,
            )

        return escaped_content

    @staticmethod
    def build_reply_markup(code: str) -> Dict[str, Any]:
        """Create inline keyboard with glass copy button."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "کپی کد تایید",
                        "copy_text": {
                            "text": code,
                        },
                    }
                ]
            ]
        }

    async def send_text(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send message text to Telegram, splitting long messages if necessary."""
        if not self.is_configured():
            logger.warning("Telegram bot credentials (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID) are not configured.")
            return False

        max_chunk = 4000
        chunks = [text[i:i + max_chunk] for i in range(0, len(text), max_chunk)]

        async with httpx.AsyncClient(timeout=15.0) as client:
            success = True
            for idx, chunk in enumerate(chunks):
                payload: Dict[str, Any] = {
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                # Attach inline keyboard button to the last chunk
                if reply_markup and idx == len(chunks) - 1:
                    payload["reply_markup"] = reply_markup

                try:
                    resp = await client.post(self.api_url, json=payload)
                    res_json = resp.json()
                    if resp.status_code == 200 and res_json.get("ok"):
                        logger.info("Message successfully delivered to Telegram.")
                    else:
                        logger.error(f"Failed to send message to Telegram: {resp.text}")
                        # Fallback: retry without entities or reply_markup if Telegram rejected
                        retry = False
                        if "can't parse entities" in resp.text:
                            payload.pop("parse_mode", None)
                            retry = True
                        if "reply_markup" in payload and ("BUTTON_TYPE_INVALID" in resp.text or "copy_text" in resp.text):
                            payload.pop("reply_markup", None)
                            retry = True
                        if retry:
                            retry_resp = await client.post(self.api_url, json=payload)
                            if retry_resp.status_code == 200 and retry_resp.json().get("ok"):
                                logger.info("Message delivered to Telegram after fallback.")
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
        sender_username: Optional[str] = None,
        attachment_name: Optional[str] = None,
        attachment_url: Optional[str] = None,
    ) -> bool:
        """Format and forward Amoozeshyar message to Telegram with copy code button."""
        code = self.extract_otp_code(content)
        formatted = self.format_amoozeshyar_message(
            content=content,
            code=code,
        )
        reply_markup = self.build_reply_markup(code) if code else None
        return await self.send_text(formatted, parse_mode="HTML", reply_markup=reply_markup)
