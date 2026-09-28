import asyncio
import re
import sys
from typing import Optional

from config import load_session, save_session
from igap_client import IGapClient, IGapError


def sanitize_phone_number(raw_input: str) -> Optional[int]:
    """Validate and sanitize Iranian mobile number to standard integer format."""
    cleaned = re.sub(r"[^\d]", "", raw_input.strip())
    # Remove leading 98 if full country code was provided
    if cleaned.startswith("98") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    # Remove leading 0 if local mobile number format was provided
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    # Mobile numbers in Iran must be 10 digits starting with 9 (e.g., 9123456789)
    if len(cleaned) == 10 and cleaned.startswith("9"):
        return int(cleaned)
    return None


async def check_existing_session(client: IGapClient) -> bool:
    """Check if existing session token is still valid."""
    session = load_session()
    token = session.get("token")
    if not token:
        return False

    print("\n🔍 Checking existing saved session...")
    try:
        await client.login(token)
        print("✅ You are already logged in with your saved session!")
        phone = session.get("phone_number", "Unknown")
        print(f"📱 Connected Phone: {phone}")
        return True
    except Exception as e:
        print(f"⚠️ Existing session is expired or invalid: {e}")
        return False


async def run_login_flow() -> None:
    print("=" * 60)
    print("🚀 iGap Authenticator & Login Setup")
    print("=" * 60)

    client = IGapClient()
    try:
        await client.connect()
    except Exception as e:
        print(f"❌ Failed to connect to iGap server: {e}")
        sys.exit(1)

    # Check existing session
    if await check_existing_session(client):
        choice = input("\nDo you want to log in with a new phone number? (y/N): ").strip().lower()
        if choice not in ("y", "yes"):
            print("\nLogin cancelled. Existing session preserved.")
            await client.close()
            return

    # Prompt for phone number
    phone_int = None
    while not phone_int:
        phone_input = input("\n📱 Enter your phone number (e.g. 09123456789): ").strip()
        phone_int = sanitize_phone_number(phone_input)
        if not phone_int:
            print("❌ Invalid phone number format. Please enter a valid 11-digit Iranian mobile number.")

    print(f"\n📩 Requesting verification code for 0{phone_int}...")
    try:
        reg_res = await client.register(phone_int)
    except IGapError as e:
        print(f"❌ iGap Error: {e}")
        await client.close()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error while requesting OTP code: {e}")
        await client.close()
        sys.exit(1)

    print("✅ Verification code sent! Check your SMS or iGap app notifications.")

    # Prompt for OTP verification code
    verify_token = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        code_input = input(f"\n🔑 Enter the verification code (attempt {attempt}/{max_attempts}): ").strip()
        code_clean = re.sub(r"[^\d]", "", code_input)

        if not code_clean:
            print("❌ Please enter numbers only.")
            continue

        try:
            print("⏳ Verifying code...")
            verify_res = await client.verify(int(code_clean), reg_res.username)
            verify_token = verify_res.token
            print("✅ Verification code accepted!")
            break
        except IGapError as e:
            print(f"❌ Verification failed: {e}")
        except Exception as e:
            print(f"❌ Error during verification: {e}")

    if not verify_token:
        print("\n❌ Maximum verification attempts exceeded. Please try again.")
        await client.close()
        sys.exit(1)

    # Finalize login and save session
    print("⏳ Activating session...")
    try:
        await client.login(verify_token)
        save_session({
            "token": verify_token,
            "phone_number": f"0{phone_int}",
            "user_id": reg_res.user_id,
            "username": reg_res.username,
        })
        print("\n" + "=" * 60)
        print("🎉 Login completed successfully!")
        print("💾 Session credentials saved to session.json.")
        print("👉 You can now run the forwarder service with:")
        print("   uv run python main.py")
        print("=" * 60)
    except Exception as e:
        print(f"❌ Error finalizing session: {e}")
    finally:
        await client.close()


def main():
    try:
        asyncio.run(run_login_flow())
    except (KeyboardInterrupt, EOFError):
        print("\n\nOperation aborted by user.")


if __name__ == "__main__":
    main()
