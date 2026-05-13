"""
logic/comment_handler.py
Handler untuk Auto-Reply Komentar di Postingan Halaman/Grup Facebook.
Alur: komentar masuk → balas di komentar (singkat) → kirim DM detail produk.
"""

import logging
import os
import httpx
from dotenv import load_dotenv

from logic.ai_engine import get_product_detail_message
from logic.anti_spam import comment_reply_delay, reply_delay, check_rate_limit
from logic.activity_logger import log_activity
from logic.messenger_handler import send_message

load_dotenv()
logger = logging.getLogger(__name__)

FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v25.0")
FB_API_BASE = f"https://graph.facebook.com/{FB_GRAPH_API_VERSION}"

# Kata kunci komentar yang memicu auto-reply
TRIGGER_KEYWORDS = [
    "harga", "price", "berapa", "beli", "order", "pesan", "minat",
    "info", "detail", "stok", "ready", "available", "dm", "inbox",
    "minta info", "pengen beli", "mau beli", "cara order", "bisa beli"
]

# Balasan komentar publik yang variatif
COMMENT_REPLIES = [
    "Halo kak! 👋 Terima kasih sudah tertarik ya! Sudah kami kirim detail lengkapnya ke DM/Inbox kak, cek ya! 📩",
    "Hai! 😊 Info produk lengkap sudah kami kirim ke inbox kak ya! Cek DM-nya 📬",
    "Terima kasih kakak! 🙏 Detail harga & stok sudah kami DM kan, cek inbox Facebook-nya ya! ✉️",
    "Halo kak, info lengkapnya sudah kami kirim ke pesan pribadi ya! Cek DM kak 😊📩",
    "Hai kak! Detail produk & harga terbaru sudah kami kirim ke inbox ya! 👋📬",
]

import random


def _should_reply(comment_text: str) -> bool:
    """Cek apakah komentar perlu dibalas berdasarkan keyword."""
    comment_lower = comment_text.lower()
    return any(kw in comment_lower for kw in TRIGGER_KEYWORDS)


async def reply_to_comment(comment_id: str, reply_text: str) -> bool:
    """
    Balas komentar di postingan Facebook secara publik.
    
    Args:
        comment_id: ID komentar yang akan dibalas
        reply_text: Teks balasan
    """
    url = f"{FB_API_BASE}/{comment_id}/comments"
    params = {
        "message": reply_text,
        "access_token": FB_PAGE_ACCESS_TOKEN
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, params=params)

        if resp.status_code == 200:
            logger.info(f"✅ Komentar dibalas: comment_id={comment_id}")
            return True
        else:
            logger.error(f"❌ Gagal balas komentar {comment_id}: {resp.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Error balas komentar: {e}")
        return False


async def handle_comment(
    comment_id: str,
    commenter_psid: str,
    comment_text: str,
    post_id: str = ""
):
    """
    Handler utama untuk komentar masuk.
    
    Alur:
    1. Cek apakah komentar relevan (ada keyword trigger)
    2. Rate limit check
    3. Jeda acak (anti-spam)
    4. Balas komentar publik dengan pesan singkat
    5. Kirim DM detail produk ke commenter
    """
    logger.info(
        f"💬 Komentar dari {commenter_psid[:8]}... | "
        f"Post: {post_id} | Teks: {comment_text[:50]}"
    )

    # 1. Cek keyword trigger
    if not _should_reply(comment_text):
        logger.debug("ℹ️ Komentar tidak mengandung keyword trigger, skip.")
        return

    # 2. Rate limit check
    if not check_rate_limit(commenter_psid):
        logger.warning(f"⚠️ Rate limit untuk commenter {commenter_psid[:8]}...")
        return

    # Log komentar masuk
    log_activity(
        event_type="COMMENT_IN",
        fb_psid=commenter_psid,
        message_in=comment_text,
        detail=f"comment_id={comment_id}"
    )

    # 3. Jeda acak sebelum reply (15-45 detik)
    await comment_reply_delay()

    # 4. Balas komentar publik (pesan singkat)
    public_reply = random.choice(COMMENT_REPLIES)
    comment_success = await reply_to_comment(comment_id, public_reply)

    if comment_success:
        log_activity(
            event_type="COMMENT_REPLIED",
            fb_psid=commenter_psid,
            message_out=public_reply,
            detail=f"comment_id={comment_id}"
        )

    # 5. Kirim DM detail produk (setelah delay tambahan)
    import asyncio
    await asyncio.sleep(random.uniform(5, 15))  # Jeda 5-15 detik sebelum DM

    dm_intro = (
        "Halo kak! 😊 Terima kasih sudah tertarik dengan produk kami.\n"
        "Ini dia informasi lengkap produk yang kami punya ya! 👇\n\n"
    )
    product_detail = get_product_detail_message()
    full_dm = dm_intro + product_detail

    dm_success = await send_message(commenter_psid, full_dm)

    if dm_success:
        log_activity(
            event_type="DM_PRODUCT_SENT",
            fb_psid=commenter_psid,
            detail="Detail produk dikirim via DM setelah komentar"
        )
    else:
        logger.warning(
            f"⚠️ Gagal kirim DM ke {commenter_psid[:8]}... "
            "(User mungkin belum pernah chat page ini)"
        )
