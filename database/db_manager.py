"""
database/db_manager.py
Manajer database SQLite untuk menyimpan data pelanggan,
riwayat percakapan, dan status human handoff.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# Pastikan folder database ada
DB_PATH = Path(__file__).parent / "customers.db"

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Membuat dan mengembalikan koneksi SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Akses kolom dengan nama
    return conn


def init_db():
    """Inisialisasi semua tabel database. Dipanggil saat startup."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Tabel data pelanggan / lead
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fb_psid         TEXT UNIQUE NOT NULL,
                nama            TEXT,
                whatsapp        TEXT,
                email           TEXT,
                status          TEXT DEFAULT 'prospect',
                source          TEXT DEFAULT 'messenger',
                notes           TEXT,
                created_at      TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at      TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # Tabel riwayat percakapan (untuk konteks AI)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fb_psid     TEXT NOT NULL,
                role        TEXT NOT NULL,
                message     TEXT NOT NULL,
                timestamp   TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # Tabel status human handoff
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS handoff_status (
                fb_psid         TEXT PRIMARY KEY,
                is_active       INTEGER DEFAULT 0,
                reason          TEXT,
                activated_at    TEXT,
                resolved_at     TEXT
            )
        """)

        conn.commit()
        logger.info("✅ Database diinisialisasi.")


# ──────────────────────────────────────────────
#  CUSTOMER FUNCTIONS
# ──────────────────────────────────────────────

def upsert_customer(fb_psid: str, **kwargs) -> dict:
    """
    Buat atau update data pelanggan berdasarkan PSID.
    kwargs: nama, whatsapp, email, status, source, notes
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Cek apakah sudah ada
        cursor.execute("SELECT * FROM customers WHERE fb_psid = ?", (fb_psid,))
        existing = cursor.fetchone()

        if existing:
            # Update field yang diberikan
            fields = ", ".join(f"{k} = ?" for k in kwargs)
            fields += ", updated_at = datetime('now', 'localtime')"
            values = list(kwargs.values()) + [fb_psid]
            cursor.execute(f"UPDATE customers SET {fields} WHERE fb_psid = ?", values)
        else:
            # Insert baru
            kwargs["fb_psid"] = fb_psid
            columns = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            cursor.execute(
                f"INSERT INTO customers ({columns}) VALUES ({placeholders})",
                list(kwargs.values())
            )

        conn.commit()

        cursor.execute("SELECT * FROM customers WHERE fb_psid = ?", (fb_psid,))
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_customer(fb_psid: str) -> Optional[Dict]:
    """Ambil data pelanggan berdasarkan PSID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM customers WHERE fb_psid = ?", (fb_psid,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_leads() -> List[Dict]:
    """Ambil semua pelanggan yang sudah menjadi lead (ada nomor WA)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM customers WHERE whatsapp IS NOT NULL ORDER BY created_at DESC"
        )
        return [dict(r) for r in cursor.fetchall()]


# ──────────────────────────────────────────────
#  CONVERSATION HISTORY FUNCTIONS
# ──────────────────────────────────────────────

def save_message(fb_psid: str, role: str, message: str):
    """Simpan satu pesan ke riwayat percakapan."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (fb_psid, role, message) VALUES (?, ?, ?)",
            (fb_psid, role, message)
        )
        conn.commit()


def get_history(fb_psid: str, limit: int = 10) -> List[Dict]:
    """
    Ambil riwayat percakapan terakhir untuk satu user.
    Mengembalikan list {'role': ..., 'message': ...}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, message FROM conversations
            WHERE fb_psid = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (fb_psid, limit)
        )
        rows = cursor.fetchall()
        # Balik urutan agar kronologis
        return [{"role": r["role"], "message": r["message"]} for r in reversed(rows)]


def clear_history(fb_psid: str):
    """Hapus riwayat percakapan (reset context)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM conversations WHERE fb_psid = ?", (fb_psid,))
        conn.commit()


# ──────────────────────────────────────────────
#  HUMAN HANDOFF FUNCTIONS
# ──────────────────────────────────────────────

def set_handoff(fb_psid: str, active: bool, reason: str = ""):
    """Aktifkan atau nonaktifkan mode human handoff untuk user."""
    with get_connection() as conn:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if active:
            conn.execute(
                """
                INSERT INTO handoff_status (fb_psid, is_active, reason, activated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(fb_psid) DO UPDATE SET
                    is_active = 1, reason = ?, activated_at = ?, resolved_at = NULL
                """,
                (fb_psid, reason, now, reason, now)
            )
        else:
            conn.execute(
                """
                INSERT INTO handoff_status (fb_psid, is_active, resolved_at)
                VALUES (?, 0, ?)
                ON CONFLICT(fb_psid) DO UPDATE SET
                    is_active = 0, resolved_at = ?
                """,
                (fb_psid, now, now)
            )
        conn.commit()


def is_handoff_active(fb_psid: str) -> bool:
    """Cek apakah user sedang dalam mode handoff ke admin manusia."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_active FROM handoff_status WHERE fb_psid = ?", (fb_psid,)
        )
        row = cursor.fetchone()
        return bool(row and row["is_active"])
