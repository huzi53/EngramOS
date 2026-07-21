"""Telegram long-polling capture bot. No webhook, no public endpoint — outbound-only
getUpdates polling, run as its own compose service (`command: python bot.py`).
Reuses store_capture() from capture.py: one capture pipeline (dedup + storage + insert),
this file is just another caller inside the compose network.
"""
import os
import time

import httpx

from capture import store_capture
from db import get_conn

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_ALLOWED_CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"


def scrub(e: Exception) -> str:
    # httpx exception strings embed the full request URL, which contains TOKEN —
    # never let it hit logs.
    return str(e).replace(TOKEN, "***") if TOKEN else str(e)


def get_user_id() -> str:
    # api's startup upserts the user row; retry rather than crash-loop if the bot wins the race.
    for attempt in range(30):
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (os.environ["AUTH_USERNAME"],))
            row = cur.fetchone()
            if row:
                return str(row[0])
        print("waiting for api to create the user row...")
        time.sleep(2)
    raise RuntimeError("user row never appeared — is the api service running?")


def download_file(client: httpx.Client, file_id: str) -> bytes:
    r = client.get(f"{API}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    r = client.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=60)
    r.raise_for_status()
    return r.content


def handle_message(client: httpx.Client, user_id: str, msg: dict) -> str:
    meta = {"telegram_message_id": msg["message_id"], "chat_id": msg["chat"]["id"]}
    if "forward_from" in msg or "forward_from_chat" in msg:
        meta["forward_from"] = msg.get("forward_from") or msg.get("forward_from_chat")

    media = None
    file_name = None
    mime = None
    if "photo" in msg:
        media = msg["photo"][-1]  # largest size
        file_name, mime = "photo.jpg", "image/jpeg"
    elif "document" in msg:
        media = msg["document"]
        file_name = media.get("file_name")
        mime = media.get("mime_type")
    elif "voice" in msg:
        media = msg["voice"]
        file_name, mime = "voice.ogg", media.get("mime_type", "audio/ogg")
    elif "audio" in msg:
        media = msg["audio"]
        file_name = media.get("file_name", "audio")
        mime = media.get("mime_type")

    if media:
        file_bytes = download_file(client, media["file_id"])
        result = store_capture(
            user_id, "telegram",
            text=msg.get("caption"), file_bytes=file_bytes, file_name=file_name, mime=mime, meta=meta,
        )
    elif "text" in msg:
        result = store_capture(user_id, "telegram", text=msg["text"], meta=meta)
    else:
        return None  # unsupported update, nothing to save

    return "Already saved" if result["duplicate"] else "Saved ✅"


def run():
    user_id = get_user_id()
    print(f"polling as {user_id}")
    offset = None
    with httpx.Client() as client:
        while True:
            try:
                r = client.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=60)
                r.raise_for_status()
                updates = r.json()["result"]
            except Exception as e:
                print(f"getUpdates failed: {scrub(e)}")
                time.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1  # advance always — a poison message must not wedge the loop
                msg = update.get("message")
                if not msg:
                    continue
                if msg["chat"]["id"] != ALLOWED_CHAT_ID:
                    continue  # trust boundary: silently drop updates from anyone else

                try:
                    reply = handle_message(client, user_id, msg)
                except Exception as e:
                    print(f"capture failed: {scrub(e)}")
                    reply = "Save failed, resend"

                if reply:
                    try:
                        client.post(f"{API}/sendMessage", json={"chat_id": msg["chat"]["id"], "text": reply}, timeout=30)
                    except Exception as e:
                        print(f"sendMessage failed: {scrub(e)}")  # capture already saved; a lost reply isn't worth crashing the loop


# ponytail: in-memory offset only — blake2b dedup makes reprocessing after a restart
# idempotent (ON CONFLICT DO NOTHING), so no persisted offset needed. Add one only if
# duplicate "Saved" replies after a restart ever actually annoy.
if __name__ == "__main__":
    run()
