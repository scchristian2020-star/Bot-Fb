"""
logic/activity_logger.py
Sistem logging aktivitas ke file activity_log.txt dan console.
Mencatat semua interaksi bot untuk audit dan troubleshooting.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LOG_FILE = os.getenv("LOG_FILE", "activity_log.txt")
# Railway pakai /tmp untuk file sementara (filesystem read-only)
_base = Path("/tmp") if os.path.exists("/tmp") else Path(__file__).parent.parent
LOG_PATH = _base / LOG_FILE

# ──────────────────────────────────────────────
#  Setup logging ke file + console
# ──────────────────────────────────────────────

def setup_logging():
    """Setup logging handler untuk file dan console."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except Exception:
        pass  # Tidak bisa tulis file log (filesystem read-only di Railway)

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=handlers
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ──────────────────────────────────────────────
#  Fungsi log khusus aktivitas bot
# ──────────────────────────────────────────────

ACTIVITY_LOGGER = logging.getLogger("activity")


def log_activity(
    event_type: str,
    fb_psid: str = "",
    detail: str = "",
    message_in: str = "",
    message_out: str = "",
):
    """
    Catat satu event aktivitas bot ke log.

    Args:
        event_type: Jenis event (MESSAGE_IN, MESSAGE_OUT, INTENT_DETECTED, dll.)
        fb_psid: Facebook PSID pengguna
        detail: Detail tambahan
        message_in: Pesan yang diterima dari user
        message_out: Pesan yang dikirim bot
    """
    psid_short = fb_psid[:8] + "..." if len(fb_psid) > 8 else fb_psid

    log_parts = [f"[{event_type}]"]
    if fb_psid:
        log_parts.append(f"PSID={psid_short}")
    if message_in:
        # Potong pesan panjang
        msg_preview = message_in[:80] + "..." if len(message_in) > 80 else message_in
        log_parts.append(f'IN="{msg_preview}"')
    if message_out:
        msg_preview = message_out[:80] + "..." if len(message_out) > 80 else message_out
        log_parts.append(f'OUT="{msg_preview}"')
    if detail:
        log_parts.append(f"DETAIL={detail}")

    ACTIVITY_LOGGER.info(" | ".join(log_parts))


def log_event(event_type: str, detail: str = ""):
    """Log event sistem (bukan interaksi user)."""
    ACTIVITY_LOGGER.info(f"[{event_type}] {detail}")
