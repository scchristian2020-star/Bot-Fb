"""
logic/messenger_handler.py
Handler utama untuk pesan Direct Message (DM) di Facebook Messenger.
Mengelola alur: terima pesan → cek handoff → deteksi intent → generate AI reply → kirim.
"""

import logging
import os
import httpx
from dotenv import load_dotenv

from database.db_manager import (
    save_message, get_history, upsert_customer,
    is_handoff_active, get_customer
)
from logic.ai_engine import (
    detect_intent, generate_reply, extract_whatsapp_number,
    get_lead_capture_message, get_wa_received_message, get_product_detail_message
)
from logic.human_handoff import activate_handoff, deactivate_handoff
from logic.anti_spam import reply_delay, check_rate_limit
from logic.activity_logger import log_activity
from logic.admin_commands import (
    is_admin, is_admin_command, is_blocked, handle_admin_command
)

load_dotenv()
logger = logging.getLogger(__name__)

FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v25.0")
FB_API_BASE = f"https://graph.facebook.com/{FB_GRAPH_API_VERSION}"

# State sementara untuk lead capture (menunggu nomor WA)
# {psid: True} → user sedang diminta nomor WA
_awaiting_wa: dict[str, bool] = {}


async def send_message(recipient_id: str, text: str) -> bool:
    """
    Kirim pesan teks ke pengguna via Messenger API.
    Returns True jika berhasil.
    """
    url = f"{FB_API_BASE}/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    params = {"access_token": FB_PAGE_ACCESS_TOKEN}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload, params=params)

        if resp.status_code == 200:
            logger.debug(f"✅ Pesan terkirim ke {recipient_id[:8]}...")
            log_activity(
                event_type="MESSAGE_OUT",
                fb_psid=recipient_id,
                message_out=text
            )
            return True
        else:
            logger.error(f"❌ Send message error {resp.status_code}: {resp.text}")
            return False

    except httpx.TimeoutException:
        logger.error(f"❌ Timeout saat mengirim pesan ke {recipient_id[:8]}...")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error saat kirim pesan: {e}")
        return False


async def handle_dm(sender_id: str, message_text: str):
    """
    Handler utama untuk pesan DM masuk.
    
    Alur:
    1. Rate limit check
    2. Log pesan masuk
    3. Cek admin command (#resume)
    4. Cek human handoff aktif
    5. Cek apakah menunggu nomor WA (lead capture)
    6. Deteksi intent
    7. Generate & kirim balasan
    """
    logger.info(f"📨 DM masuk dari {sender_id[:8]}... : {message_text[:50]}")

    # 1. Rate limit check
    if not check_rate_limit(sender_id):
        logger.warning(f"⚠️ Rate limit untuk {sender_id[:8]}... skip.")
        return

    # 2. Log pesan masuk & simpan ke history
    log_activity(
        event_type="MESSAGE_IN",
        fb_psid=sender_id,
        message_in=message_text
    )
    save_message(sender_id, "user", message_text)

    # 3. CEK ADMIN COMMAND — hanya admin yang boleh
    if is_admin_command(message_text):
        if is_admin(sender_id):
            log_activity(
                event_type="ADMIN_CMD",
                fb_psid=sender_id,
                detail=message_text[:80]
            )
            reply = await handle_admin_command(sender_id, message_text)
            await send_message(sender_id, reply)
        else:
            # Bukan admin — abaikan atau anggap pesan biasa
            logger.warning(
                f"Pesan '#' dari non-admin {sender_id[:8]}... diabaikan."
            )
            await send_message(
                sender_id,
                "Maaf, perintah ini hanya untuk admin. 🙏"
            )
        return

    # 4. CEK USER DIBLOKIR
    if is_blocked(sender_id):
        logger.info(f"Pesan dari user terblokir {sender_id[:8]}... diabaikan.")
        return
    if is_handoff_active(sender_id):
        logger.info(f"🔒 Handoff aktif untuk {sender_id[:8]}..., skip AI response.")
        log_activity(
            event_type="HANDOFF_SKIP",
            fb_psid=sender_id,
            detail="AI dilewati karena handoff aktif"
        )
        return

    # 5. Cek apakah sedang menunggu nomor WA (lead capture)
    if _awaiting_wa.get(sender_id):
        wa_number = extract_whatsapp_number(message_text)
        if wa_number:
            # Nomor WA berhasil didapat → simpan ke DB
            upsert_customer(sender_id, whatsapp=wa_number, status="lead")
            _awaiting_wa.pop(sender_id, None)

            log_activity(
                event_type="LEAD_CAPTURED",
                fb_psid=sender_id,
                detail=f"WA: {wa_number}"
            )

            await reply_delay()
            reply = get_wa_received_message(wa_number)
            await send_message(sender_id, reply)
            save_message(sender_id, "assistant", reply)
        else:
            # Nomor tidak terdeteksi, minta lagi
            await reply_delay()
            retry_msg = (
                "Maaf kak, nomor WhatsApp-nya belum kebaca 😅\n\n"
                "Bisa tulis nomor WA-nya ya? Contoh: 081234567890"
            )
            await send_message(sender_id, retry_msg)
        return

    # 6. Deteksi intent dari pesan
    intent = detect_intent(message_text)
    log_activity(
        event_type="INTENT_DETECTED",
        fb_psid=sender_id,
        detail=f"Intent: {intent}"
    )

    # 7. Ambil customer info untuk nama
    customer = get_customer(sender_id) or {}
    customer_name = customer.get("nama", "Pelanggan")

    # ── Tangani berdasarkan intent ──

    if intent == "ANGRY":
        await reply_delay()
        await activate_handoff(sender_id, reason="ANGRY", customer_name=customer_name)
        return

    if intent == "HUMAN_REQUEST":
        await reply_delay()
        await activate_handoff(sender_id, reason="HUMAN_REQUEST", customer_name=customer_name)
        return

    if intent == "LEAD_BUY":
        # Generate AI reply dulu, lalu tawarkan lead capture
        history = get_history(sender_id)
        await reply_delay()
        ai_reply = generate_reply(message_text, history)
        await send_message(sender_id, ai_reply)
        save_message(sender_id, "assistant", ai_reply)

        # Kirim pesan lead capture setelah delay pendek
        import asyncio
        await asyncio.sleep(3)
        lead_msg = get_lead_capture_message()
        await send_message(sender_id, lead_msg)
        save_message(sender_id, "assistant", lead_msg)

        # Set flag menunggu nomor WA
        _awaiting_wa[sender_id] = True
        log_activity(event_type="LEAD_INITIATED", fb_psid=sender_id)
        return

    # Intent GREETING atau GENERAL → jawab dengan AI
    history = get_history(sender_id)
    await reply_delay()
    ai_reply = generate_reply(message_text, history)

    if not ai_reply:
        ai_reply = "Maaf, saya sedang ada gangguan. Silakan coba lagi ya kak 🙏"

    await send_message(sender_id, ai_reply)
    save_message(sender_id, "assistant", ai_reply)
