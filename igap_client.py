import asyncio
import logging
import os
import random
import string
import struct
from typing import Callable, Coroutine, Dict, Optional, Any

import websockets
from websockets.asyncio.client import ClientConnection
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Ensure protobuf package is imported
import igap_proto
import ConnectionSecuring_pb2
import Heartbeat_pb2
import UserRegister_pb2
import UserVerify_pb2
import UserLogin_pb2
import ChatSendMessage_pb2
import ChannelSendMessage_pb2
import GroupSendMessage_pb2
import ClientResolveUsername_pb2
import Error_pb2
import Global_pb2

from config import (
    IGAP_WS_URL,
    EMBEDDED_PUBLIC_PEM,
    ACTION_CONNECTION_SYMMETRIC_KEY,
    ACTION_HEARTBEAT,
    ACTION_USER_REGISTER,
    ACTION_USER_VERIFY,
    ACTION_USER_LOGIN,
    ACTION_CLIENT_RESOLVE_USERNAME,
    ACTION_CHAT_SEND_MESSAGE_RESPONSE,
    ACTION_CHANNEL_SEND_MESSAGE_RESPONSE,
    ACTION_GROUP_SEND_MESSAGE_RESPONSE,
    ACTION_ERROR,
)

logger = logging.getLogger("igap_client")


class IGapError(Exception):
    def __init__(self, major_code: int, minor_code: int, message: str):
        self.major_code = major_code
        self.minor_code = minor_code
        self.message = message
        super().__init__(f"iGap Error [{major_code}:{minor_code}]: {message}")


class IGapClient:
    def __init__(self, ws_url: str = IGAP_WS_URL):
        self.ws_url = ws_url
        self.ws: Optional[ClientConnection] = None
        self.is_connected = False
        self.is_secure = False

        self.symmetric_key: Optional[bytes] = None
        self.symmetric_method: Optional[str] = None
        self.iv_size: int = 16
        self.heartbeat_interval: int = 50

        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._message_callbacks = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._is_closing = False

    @staticmethod
    def generate_request_id(length: int = 10) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def _rsa_encrypt(data: bytes, pub_pem: bytes) -> bytes:
        pub_key = serialization.load_pem_public_key(pub_pem)
        return pub_key.encrypt(data, asym_padding.PKCS1v15())

    def _aes_encrypt(self, data: bytes) -> bytes:
        if not self.is_secure or not self.symmetric_key:
            raise RuntimeError("Connection is not secured yet.")
        iv = os.urandom(self.iv_size)
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.symmetric_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return iv + ciphertext

    def _aes_decrypt(self, data: bytes) -> bytes:
        if not self.is_secure or not self.symmetric_key:
            raise RuntimeError("Connection is not secured yet.")
        if len(data) <= self.iv_size:
            raise ValueError("Payload size is too short for AES decryption.")
        iv = data[:self.iv_size]
        ciphertext = data[self.iv_size:]
        cipher = Cipher(algorithms.AES(self.symmetric_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()

    async def connect(self) -> None:
        """Establish WebSocket connection and complete handshake security protocol."""
        logger.info(f"Connecting to iGap server: {self.ws_url}")
        self._is_closing = False
        self.ws = await websockets.connect(self.ws_url, max_size=10 * 1024 * 1024)
        self.is_connected = True

        # Step 1: Receive server public key & security parameters (Action 30001)
        raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=15.0)
        action_id = struct.unpack("<H", raw_msg[:2])[0]
        if action_id != 30001:
            raise RuntimeError(f"Expected action 30001, but received {action_id}.")

        sec_res = ConnectionSecuring_pb2.ConnectionSecuringResponse()
        sec_res.ParseFromString(raw_msg[2:])

        self.heartbeat_interval = max(sec_res.heartbeat_interval or 50, 15)
        sym_key_len = sec_res.symmetric_key_length or 32
        self.symmetric_key = os.urandom(sym_key_len)

        # Step 2: Encrypt symmetric key with server public key
        key1 = self._rsa_encrypt(self.symmetric_key, sec_res.public_key.encode("utf-8"))

        # Step 3: Chunk and encrypt with embedded public key
        chunk_size = sec_res.secondary_chunk_size or 128
        secure_key = b""
        for i in range(0, len(key1), chunk_size):
            chunk = key1[i:i + chunk_size]
            secure_key += self._rsa_encrypt(chunk, EMBEDDED_PUBLIC_PEM)

        # Send encrypted symmetric key to server (Action 2)
        req_sym = ConnectionSecuring_pb2.ConnectionSymmetricKey()
        req_sym.request.id = self.generate_request_id()
        req_sym.symmetric_key = secure_key
        req_sym.version = 2

        payload = struct.pack("<H", ACTION_CONNECTION_SYMMETRIC_KEY) + req_sym.SerializeToString()
        await self.ws.send(payload)

        # Receive security handshake confirmation (Action 30002)
        resp_raw = await asyncio.wait_for(self.ws.recv(), timeout=15.0)
        resp_act = struct.unpack("<H", resp_raw[:2])[0]
        if resp_act != 30002:
            raise RuntimeError(f"Handshake failed. Received action: {resp_act}")

        key_resp = ConnectionSecuring_pb2.ConnectionSymmetricKeyResponse()
        key_resp.ParseFromString(resp_raw[2:])
        if key_resp.status != ConnectionSecuring_pb2.ConnectionSymmetricKeyResponse.Status.ACCEPTED:
            raise RuntimeError("Server rejected the symmetric security key.")

        self.symmetric_method = key_resp.symmetric_method
        self.iv_size = key_resp.symmetric_iv_size or 16
        self.is_secure = True
        logger.info("iGap connection secured with end-to-end symmetric encryption.")

        # Start background tasks for incoming messages and periodic heartbeat
        self._receiver_task = asyncio.create_task(self._receiver_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Periodically send Heartbeats to maintain session keepalive."""
        interval = max(self.heartbeat_interval - 5, 20)
        try:
            while self.is_connected and not self._is_closing:
                await asyncio.sleep(interval)
                if not self.is_connected or not self.ws:
                    break
                try:
                    hb = Heartbeat_pb2.Heartbeat()
                    hb.request.id = self.generate_request_id()
                    await self._send_packet(ACTION_HEARTBEAT, hb.SerializeToString())
                    logger.debug("Heartbeat keepalive packet sent.")
                except Exception as e:
                    logger.warning(f"Error sending heartbeat keepalive: {e}")
                    break
        except asyncio.CancelledError:
            pass

    async def _send_packet(self, action_id: int, payload: bytes) -> None:
        """Frame and send packet over WebSocket (with AES encryption if active)."""
        packet = struct.pack("<H", action_id) + payload
        if self.is_secure:
            packet = self._aes_encrypt(packet)
        if self.ws:
            await self.ws.send(packet)

    async def send_request(self, action_id: int, pb_message: Any, timeout: float = 20.0) -> Any:
        """Send protobuf request and wait for corresponding response by request ID."""
        if not self.is_connected or not self.ws:
            raise ConnectionError("Client is not connected to server.")

        req_id = getattr(pb_message.request, "id", None)
        if not req_id:
            req_id = self.generate_request_id()
            pb_message.request.id = req_id

        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        try:
            await self._send_packet(action_id, pb_message.SerializeToString())
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_requests.pop(req_id, None)

    async def _receiver_loop(self) -> None:
        """Continuous loop to receive incoming frames, decrypt, and route messages."""
        try:
            while self.is_connected and self.ws and not self._is_closing:
                raw_data = await self.ws.recv()
                if not raw_data:
                    continue

                if self.is_secure:
                    try:
                        data = self._aes_decrypt(raw_data)
                    except Exception as e:
                        logger.error(f"Failed to decrypt incoming payload: {e}")
                        continue
                else:
                    data = raw_data

                action_id = struct.unpack("<H", data[:2])[0]
                payload = data[2:]

                # Check if action is an ErrorResponse
                if action_id == ACTION_ERROR:
                    err = Error_pb2.ErrorResponse()
                    err.ParseFromString(payload)
                    req_id = err.response.id
                    if req_id and req_id in self._pending_requests:
                        fut = self._pending_requests.pop(req_id)
                        if not fut.done():
                            fut.set_exception(IGapError(err.major_code, err.minor_code, err.message))
                    else:
                        logger.warning(f"Unmatched server error response: {err.message} ({err.major_code}:{err.minor_code})")
                    continue

                # Check if this frame is a response to a pending request
                resolved = False
                for req_id, fut in list(self._pending_requests.items()):
                    if not fut.done():
                        parsed_res = self._try_extract_response_id(payload)
                        if parsed_res == req_id:
                            fut.set_result((action_id, payload))
                            resolved = True
                            break

                if not resolved:
                    # Unprompted event (Push notification or new chat message)
                    await self._handle_incoming_event(action_id, payload)

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
        except Exception as e:
            logger.error(f"Error in WebSocket receiver loop: {e}", exc_info=True)
        finally:
            self.is_connected = False
            for fut in self._pending_requests.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Connection lost while awaiting response."))
            self._pending_requests.clear()

    @staticmethod
    def _try_extract_response_id(payload: bytes) -> Optional[str]:
        """Extract response.id from protobuf payload using generic envelope."""
        try:
            env = Heartbeat_pb2.HeartbeatResponse()
            env.ParseFromString(payload)
            if env.response and env.response.id:
                return env.response.id
        except Exception:
            pass
        return None

    def on_message(self, callback: Callable[[int, Any], Coroutine[Any, Any, None]]) -> None:
        """Register a callback for incoming chat, group, or channel messages."""
        self._message_callbacks.append(callback)

    async def _handle_incoming_event(self, action_id: int, payload: bytes) -> None:
        """Dispatch incoming messages to registered listeners."""
        msg_obj = None

        if action_id == ACTION_CHAT_SEND_MESSAGE_RESPONSE:
            chat_msg = ChatSendMessage_pb2.ChatSendMessageResponse()
            chat_msg.ParseFromString(payload)
            msg_obj = chat_msg
            logger.info(f"Incoming message in private chat (Room ID: {chat_msg.room_id})")

        elif action_id == ACTION_CHANNEL_SEND_MESSAGE_RESPONSE:
            ch_msg = ChannelSendMessage_pb2.ChannelSendMessageResponse()
            ch_msg.ParseFromString(payload)
            msg_obj = ch_msg
            logger.info(f"Incoming message in channel (Room ID: {ch_msg.room_id})")

        elif action_id == ACTION_GROUP_SEND_MESSAGE_RESPONSE:
            grp_msg = GroupSendMessage_pb2.GroupSendMessageResponse()
            grp_msg.ParseFromString(payload)
            msg_obj = grp_msg
            logger.info(f"Incoming message in group (Room ID: {grp_msg.room_id})")

        if msg_obj:
            for cb in self._message_callbacks:
                try:
                    await cb(action_id, msg_obj)
                except Exception as e:
                    logger.error(f"Error in message callback handler: {e}", exc_info=True)

    # ------------------ High-Level API Methods ------------------

    async def register(self, phone_number: int, country_code: str = "IR") -> UserRegister_pb2.UserRegisterResponse:
        """Request registration OTP code for a phone number."""
        req = UserRegister_pb2.UserRegister()
        req.phone_number = phone_number
        req.country_code = country_code
        req.preference_method = UserRegister_pb2.UserRegister.VERIFY_CODE_AUTO

        action_id, payload = await self.send_request(ACTION_USER_REGISTER, req)
        res = UserRegister_pb2.UserRegisterResponse()
        res.ParseFromString(payload)
        return res

    async def verify(self, code: int, username: str) -> UserVerify_pb2.UserVerifyResponse:
        """Verify OTP code sent to user and retrieve auth session token."""
        req = UserVerify_pb2.UserVerify()
        req.code = int(code)
        req.username = str(username)

        action_id, payload = await self.send_request(ACTION_USER_VERIFY, req)
        res = UserVerify_pb2.UserVerifyResponse()
        res.ParseFromString(payload)
        return res

    async def login(self, token: str) -> UserLogin_pb2.UserLoginResponse:
        """Authenticate session using the user auth token."""
        req = UserLogin_pb2.UserLogin()
        req.token = token
        req.app_name = "AmoozeshyarNotifier"
        req.app_id = 12345
        req.app_build_version = 1
        req.app_version = "1.0.0"
        req.platform = Global_pb2.Platform.LINUX
        req.platform_version = "1.0"
        req.device = Global_pb2.Device.PC
        req.device_name = "Desktop"
        req.language = Global_pb2.Language.FA_IR

        action_id, payload = await self.send_request(ACTION_USER_LOGIN, req)
        res = UserLogin_pb2.UserLoginResponse()
        res.ParseFromString(payload)
        return res

    async def resolve_username(self, username: str) -> ClientResolveUsername_pb2.ClientResolveUsernameResponse:
        """Resolve an iGap username to get room ID or user ID details."""
        req = ClientResolveUsername_pb2.ClientResolveUsername()
        req.username = username.lstrip("@")

        action_id, payload = await self.send_request(ACTION_CLIENT_RESOLVE_USERNAME, req)
        res = ClientResolveUsername_pb2.ClientResolveUsernameResponse()
        res.ParseFromString(payload)
        return res

    async def close(self) -> None:
        """Cleanly close WebSocket connection and cancel running tasks."""
        self._is_closing = True
        self.is_connected = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self.ws:
            await self.ws.close()
