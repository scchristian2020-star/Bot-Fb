"""
logic/human_handoff.py
Menangani logika Human Handoff: mendeteksi pemicu, menonaktifkan AI,
dan mengirim notifikasi ke admin via Facebook DM dan/atau WhatsApp (Fonnte).
"""

import logging
import os
import httpx
from dotenv import load_dotenv
from database.db_manager import set_handoff, upsert_customer
from logic.activity_logger import log_activity

load_dotenv()
logger = logging.getLogger(__name__)

FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v25.0")
ADMIN_FB_PSID = os.getenv("ADMIN_FB_PSID")
ADMIN_NOTIF_FB = os.getenv("ADMIN_NOTIF_FB", "true").lower() == "true"

ADMIN_NOTIF_WA = os.getenv("ADMIN_NOTIF_WA", "false").lower() == "true"
ADMIN_WA_NUMBER = os.getenv("ADMIN_WA_NUMBER")
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")

FB_API_BASE = f"https://graph.facebook.com/{FB_GRAPH_API_VERSION}"


async def _send_fb_message(psid: str, text: str):
    """Kirim pesan Facebook Messenger ke PSID tertentu."""
    url = f"{FB_API_BASE}/me/messages"
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }
    params = {"access_token": FB_PAGE_ACCESS_TOKEN}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload, params=params)
        if resp.status_code != 200:
            logger.error(f"❌ FB send error: {resp.text}")
        return resp


async def _send_wa_fonnte(number: str, message: str):
    """Kirim pesan WhatsApp via Fonnte API."""
    if not FONNTE_TOKEN:
        logger.warning("⚠️ FONNTE_TOKEN tidak diset, skip WA notifikasi.")
        return

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": FONNTE_TOKEN},
            data={"target": number, "message": message}
        )
        if resp.status_code == 200:
            logger.info(f"✅ WA notifikasi terkirim ke {number}")
        else:
            logger.error(f"❌ Fonnte error: {resp.text}")


async def activate_handoff(sender_psid: str, reason: str, customer_name: str = "Pelanggan"):
    """
    Aktifkan human handoff untuk user:
    1. Set flag di database
    2. Notifikasi admin via FB + WA
    3. Log aktivitas
    """
    logger.info(f"🚨 Human Handoff diaktifkan untuk PSID: {sender_psid[:8]}... | Alasan: {reason}")

    # 1. Simpan status handoff ke DB
    set_handoff(sender_psid, active=True, reason=reason)
    upsert_customer(sender_psid, status="handoff")

    # 2. Balas pelanggan
    if reason == "ANGRY":
        reply_to_user = (
            "Kami sangat menyesal atas ketidaknyamanan ini 🙏\n\n"
            "Admin kami akan segera menghubungi Anda secara langsung. "
            "Mohon tunggu sebentar ya, kami prioritaskan masalah Anda! 💙"
        )
    else:  # HUMAN_REQUEST
        reply_to_user = (
            "Tentu kak! 😊 Saya sambungkan ke admin manusia kami sekarang.\n\n"
            "Admin kami akan membalas sebentar lagi. "
            "Jam operasional: Senin-Sabtu 08.00–17.00 WIB 🕐"
        )

    await _send_fb_message(sender_psid, reply_to_user)

    # 3. Notifikasi admin via Facebook DM
    if ADMIN_NOTIF_FB and ADMIN_FB_PSID:
        admin_msg = (
            f"🚨 *HANDOFF ALERT*\n\n"
            f"Pelanggan: {customer_name}\n"
            f"PSID: {sender_psid}\n"
            f"Alasan: {reason}\n\n"
            f"Silakan balas pelanggan ini secara manual di Inbox Facebook Page Anda."
        )
        await _send_fb_message(ADMIN_FB_PSID, admin_msg)
        logger.info("✅ Notifikasi FB admin terkirim.")

    # 4. Notifikasi admin via WhatsApp
    if ADMIN_NOTIF_WA and ADMIN_WA_NUMBER:
        wa_msg = (
            f"🚨 HANDOFF ALERT - {reason}\n\n"
            f"Ada pelanggan di Facebook Messenger yang perlu ditangani manual.\n"
            f"Pelanggan: {customer_name}\n"
            f"PSID: {sender_psid}\n\n"
            f"Silakan buka Inbox Facebook Page Anda sekarang."
        )
        await _send_wa_fonnte(ADMIN_WA_NUMBER, wa_msg)

    # 5. Log aktivitas
    log_activity(
        event_type="HANDOFF_ACTIVATED",
        fb_psid=sender_psid,
        detail=f"Alasan: {reason} | Nama: {customer_name}"
    )


async def deactivate_handoff(sender_psid: str):
    """
    Nonaktifkan handoff (dipanggil oleh admin via command khusus).
    Command: admin kirim pesan '#resume {psid}' ke page.
    """
    set_handoff(sender_psid, active=False)
    upsert_customer(sender_psid, status="customer")

    # Beritahu pelanggan
    await _send_fb_message(
        sender_psid,
        "Halo kak! 😊 Admin kami sudah selesai membantu. "
        "Saya (asisten otomatis) siap melayani Anda kembali. "
        "Ada yang bisa dibantu? 🙏"
    )

    log_activity(
        event_type="HANDOFF_DEACTIVATED",
        fb_psid=sender_psid,
        detail="Admin menonaktifkan handoff secara manual."
    )
    logger.info(f"✅ Handoff dinonaktifkan untuk PSID: {sender_psid[:8]}...")
