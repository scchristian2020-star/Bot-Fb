"""
logic/anti_spam.py
Sistem Random Delay & Rate Limiter untuk menghindari deteksi spam
oleh Meta. Semua fungsi pengiriman pesan harus melewati delay ini.
"""

import asyncio
import random
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Baca konfigurasi delay dari .env
REPLY_DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN", "10"))
REPLY_DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX", "30"))
GROUP_POST_DELAY_MIN = int(os.getenv("GROUP_POST_DELAY_MIN", "1800"))
GROUP_POST_DELAY_MAX = int(os.getenv("GROUP_POST_DELAY_MAX", "3600"))

# Rate limiter: {fb_psid: [timestamp_pesan_1, timestamp_pesan_2, ...]}
_rate_limit_store: dict[str, list[datetime]] = defaultdict(list)

# Batas: max pesan per user per jam
MAX_MESSAGES_PER_HOUR = 10


# ──────────────────────────────────────────────
#  DELAY FUNCTIONS
# ──────────────────────────────────────────────

async def reply_delay():
    """
    Jeda acak 10–30 detik sebelum membalas pesan/komentar.
    Simulasi perilaku manusia untuk menghindari deteksi bot.
    """
    seconds = random.uniform(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
    logger.debug(f"⏳ Reply delay: {seconds:.1f} detik...")
    await asyncio.sleep(seconds)


async def group_post_delay():
    """
    Jeda acak 30–60 menit sebelum posting di grup.
    Mencegah akun terkena rate limit posting grup.
    """
    seconds = random.uniform(GROUP_POST_DELAY_MIN, GROUP_POST_DELAY_MAX)
    menit = seconds / 60
    logger.info(f"⏳ Group post delay: {menit:.1f} menit...")
    await asyncio.sleep(seconds)


async def comment_reply_delay():
    """
    Jeda khusus untuk membalas komentar: 15–45 detik.
    Lebih panjang dari reply DM untuk keamanan ekstra.
    """
    seconds = random.uniform(15, 45)
    logger.debug(f"⏳ Comment reply delay: {seconds:.1f} detik...")
    await asyncio.sleep(seconds)


def get_random_delay_seconds(min_s: int, max_s: int) -> float:
    """Helper untuk mendapatkan nilai delay acak (sinkron)."""
    return random.uniform(min_s, max_s)


# ──────────────────────────────────────────────
#  RATE LIMITER
# ──────────────────────────────────────────────

def check_rate_limit(fb_psid: str) -> bool:
    """
    Cek apakah user masih dalam batas pengiriman pesan.
    Returns True jika BOLEH dikirim, False jika sudah melewati batas.
    """
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)

    # Bersihkan timestamp lama (> 1 jam)
    _rate_limit_store[fb_psid] = [
        ts for ts in _rate_limit_store[fb_psid] if ts > one_hour_ago
    ]

    if len(_rate_limit_store[fb_psid]) >= MAX_MESSAGES_PER_HOUR:
        logger.warning(
            f"🚫 Rate limit tercapai untuk PSID {fb_psid[:8]}... "
            f"({MAX_MESSAGES_PER_HOUR} pesan/jam)"
        )
        return False

    # Catat pesan baru
    _rate_limit_store[fb_psid].append(now)
    return True


def get_message_count(fb_psid: str) -> int:
    """Ambil jumlah pesan yang dikirim ke user dalam 1 jam terakhir."""
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    return sum(
        1 for ts in _rate_limit_store.get(fb_psid, [])
        if ts > one_hour_ago
    )


# ──────────────────────────────────────────────
#  HUMANIZER — Variasi pesan agar tidak terdeteksi template
# ──────────────────────────────────────────────

GREETINGS = [
    "Halo! 😊",
    "Hai kak! 👋",
    "Selamat datang! 🙏",
    "Halo, terima kasih sudah menghubungi kami! 😊",
    "Hai! Senang bisa membantu 😄",
]

WAIT_MESSAGES = [
    "Mohon tunggu sebentar ya kak...",
    "Baik, saya cek dulu ya... 🔍",
    "Oke, satu moment ya kak 🙏",
    "Siap! Sebentar saya carikan infonya...",
]

CLOSING_MESSAGES = [
    "Ada yang bisa saya bantu lagi? 😊",
    "Masih ada pertanyaan lain kak? 🙏",
    "Kalau ada yang kurang jelas, jangan sungkan tanya ya! 😄",
    "Semoga membantu kak! Silakan tanya lagi kapan saja 🙏",
]


def random_greeting() -> str:
    return random.choice(GREETINGS)


def random_wait() -> str:
    return random.choice(WAIT_MESSAGES)


def random_closing() -> str:
    return random.choice(CLOSING_MESSAGES)
