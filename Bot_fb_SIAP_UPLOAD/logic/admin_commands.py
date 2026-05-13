"""
logic/admin_commands.py
Sistem perintah admin untuk mengontrol bot via Facebook Messenger.
Admin mengirim pesan ke Page dengan format: #perintah [argumen]

DAFTAR PERINTAH:
  #help                 - Tampilkan semua perintah
  #status               - Status bot & statistik
  #leads                - Daftar semua leads
  #info {psid}          - Detail info satu pelanggan
  #resume {psid}        - Aktifkan kembali bot untuk user (selesai handoff)
  #pause {psid}         - Nonaktifkan bot untuk user tertentu
  #clear {psid}         - Hapus riwayat percakapan user
  #broadcast {pesan}    - Kirim pesan ke semua leads
  #block {psid}         - Blokir user dari interaksi bot
  #unblock {psid}       - Hapus blokir user
  #stats                - Statistik lengkap
  #log {n}              - Tampilkan n baris log terakhir (default 10)
  #setpromo {teks}      - Update pesan promo aktif
  #reload               - Reload produk_knowledge.json tanpa restart
"""

import logging
import os
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ADMIN_FB_PSID = os.getenv("ADMIN_FB_PSID", "")
LOG_PATH = Path(__file__).parent.parent / os.getenv("LOG_FILE", "activity_log.txt")
KNOWLEDGE_PATH = Path(__file__).parent.parent / "produk_knowledge.json"

# Set PSID yang diblokir (in-memory, reset saat restart)
_blocked_psids: set[str] = set()


def is_admin(sender_psid: str) -> bool:
    """
    Cek apakah sender adalah admin yang terdaftar.
    Admin diidentifikasi lewat ADMIN_FB_PSID di .env.
    """
    if not ADMIN_FB_PSID or ADMIN_FB_PSID in (
        "numeric_psid_akun_facebook_admin", ""
    ):
        return False
    return sender_psid == ADMIN_FB_PSID


def is_admin_command(message: str) -> bool:
    """Cek apakah pesan adalah perintah admin (diawali #)."""
    return message.strip().startswith("#")


def is_blocked(psid: str) -> bool:
    """Cek apakah user diblokir."""
    return psid in _blocked_psids


async def handle_admin_command(sender_psid: str, message: str) -> str:
    """
    Proses perintah admin dan kembalikan teks respons.
    Dipanggil dari messenger_handler.py setelah verifikasi admin.
    """
    from database.db_manager import (
        get_all_leads, get_customer, get_history,
        clear_history, set_handoff, is_handoff_active
    )

    parts = message.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    logger.info(f"[ADMIN CMD] {cmd} | args: {args[:50] if args else '-'}")

    # ── #help ──────────────────────────────────────
    if cmd == "#help":
        return """DAFTAR PERINTAH ADMIN:

#status          - Status bot & statistik cepat
#stats           - Statistik lengkap
#leads           - Semua leads & nomor WA
#info {psid}     - Detail pelanggan tertentu
#resume {psid}   - Selesai handoff, aktifkan bot
#pause {psid}    - Nonaktifkan bot untuk user ini
#clear {psid}    - Hapus history percakapan
#block {psid}    - Blokir user dari bot
#unblock {psid}  - Hapus blokir user
#broadcast {msg} - Kirim pesan ke semua leads
#log {n}         - Lihat n baris log terakhir
#reload          - Reload data produk tanpa restart"""

    # ── #status ────────────────────────────────────
    elif cmd == "#status":
        leads = get_all_leads()
        total = len(leads)
        handoffs = sum(1 for l in leads if l.get("status") == "handoff")
        wa_captured = sum(1 for l in leads if l.get("whatsapp"))
        blocked = len(_blocked_psids)

        return (
            f"STATUS BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"Total pelanggan : {total}\n"
            f"WA tersimpan    : {wa_captured}\n"
            f"Perlu handoff   : {handoffs}\n"
            f"User diblokir   : {blocked}\n"
            f"LLM Provider    : {os.getenv('LLM_PROVIDER','?').upper()}\n"
            f"Status server   : ONLINE"
        )

    # ── #stats ─────────────────────────────────────
    elif cmd == "#stats":
        leads = get_all_leads()
        by_status = {}
        by_source = {}
        for l in leads:
            s = l.get("status", "prospect")
            src = l.get("source", "messenger")
            by_status[s] = by_status.get(s, 0) + 1
            by_source[src] = by_source.get(src, 0) + 1

        status_str = "\n".join(f"  {k}: {v}" for k, v in by_status.items())
        source_str = "\n".join(f"  {k}: {v}" for k, v in by_source.items())

        return (
            f"STATISTIK LENGKAP\n\n"
            f"Total Pelanggan: {len(leads)}\n\n"
            f"Per Status:\n{status_str or '  (kosong)'}\n\n"
            f"Per Sumber:\n{source_str or '  (kosong)'}\n\n"
            f"Terblokir: {len(_blocked_psids)} user"
        )

    # ── #leads ─────────────────────────────────────
    elif cmd == "#leads":
        leads = get_all_leads()
        if not leads:
            return "Belum ada leads tersimpan."
        lines = [f"DAFTAR LEADS ({len(leads)} total):\n"]
        for i, l in enumerate(leads[:15], 1):  # Max 15 agar tidak terlalu panjang
            wa = l.get("whatsapp") or "-"
            status = l.get("status", "prospect").upper()
            psid_short = l.get("fb_psid", "")[:10]
            lines.append(f"{i}. {psid_short}... | WA: {wa} | {status}")
        if len(leads) > 15:
            lines.append(f"\n...dan {len(leads)-15} lainnya. Cek dashboard.")
        return "\n".join(lines)

    # ── #info {psid} ───────────────────────────────
    elif cmd == "#info":
        if not args:
            return "Format: #info {psid}\nContoh: #info 1234567890123456"
        customer = get_customer(args)
        if not customer:
            return f"Pelanggan dengan PSID {args} tidak ditemukan."
        history = get_history(args, limit=3)
        handoff = is_handoff_active(args)
        blocked = args in _blocked_psids

        hist_str = ""
        for h in history[-3:]:
            role = "User" if h["role"] == "user" else "Bot"
            hist_str += f"\n  [{role}]: {h['message'][:60]}..."

        return (
            f"INFO PELANGGAN\n\n"
            f"PSID     : {customer.get('fb_psid','')}\n"
            f"WA       : {customer.get('whatsapp') or '-'}\n"
            f"Status   : {customer.get('status','').upper()}\n"
            f"Sumber   : {customer.get('source','')}\n"
            f"Handoff  : {'AKTIF' if handoff else 'tidak'}\n"
            f"Blokir   : {'YA' if blocked else 'tidak'}\n"
            f"Bergabung: {customer.get('created_at','')}\n"
            f"\n3 Pesan Terakhir:{hist_str or chr(10) + '  (kosong)'}"
        )

    # ── #resume {psid} ─────────────────────────────
    elif cmd == "#resume":
        if not args:
            return "Format: #resume {psid}\nContoh: #resume 1234567890123456"
        from logic.human_handoff import deactivate_handoff
        await deactivate_handoff(args)
        return f"Handoff untuk {args[:12]}... sudah dinonaktifkan. Bot aktif kembali."

    # ── #pause {psid} ──────────────────────────────
    elif cmd == "#pause":
        if not args:
            return "Format: #pause {psid}"
        set_handoff(args, active=True, reason="ADMIN_PAUSE")
        return f"Bot untuk {args[:12]}... dinonaktifkan sementara.\nGunakan #resume {args} untuk mengaktifkan kembali."

    # ── #clear {psid} ──────────────────────────────
    elif cmd == "#clear":
        if not args:
            return "Format: #clear {psid}"
        clear_history(args)
        return f"Riwayat percakapan untuk {args[:12]}... sudah dihapus. Konteks AI direset."

    # ── #block {psid} ──────────────────────────────
    elif cmd == "#block":
        if not args:
            return "Format: #block {psid}"
        _blocked_psids.add(args)
        set_handoff(args, active=True, reason="BLOCKED")
        return f"User {args[:12]}... diblokir. Bot tidak akan merespons pesan mereka."

    # ── #unblock {psid} ────────────────────────────
    elif cmd == "#unblock":
        if not args:
            return "Format: #unblock {psid}"
        _blocked_psids.discard(args)
        set_handoff(args, active=False)
        return f"User {args[:12]}... sudah tidak diblokir. Bot aktif kembali."

    # ── #broadcast {pesan} ─────────────────────────
    elif cmd == "#broadcast":
        if not args:
            return "Format: #broadcast {pesan yang ingin dikirim ke semua leads}"

        leads = get_all_leads()
        wa_leads = [l for l in leads if l.get("whatsapp")]
        if not wa_leads:
            return "Belum ada leads dengan nomor WA untuk di-broadcast."

        # Kirim ke semua leads via Messenger (hanya yang punya riwayat chat)
        from logic.messenger_handler import send_message
        from logic.anti_spam import reply_delay
        import asyncio

        success = 0
        fail = 0
        broadcast_msg = f"[PESAN DARI ADMIN]\n\n{args}"

        for lead in leads[:50]:  # Max 50 per broadcast
            psid = lead.get("fb_psid")
            if psid:
                try:
                    ok = await send_message(psid, broadcast_msg)
                    if ok:
                        success += 1
                    else:
                        fail += 1
                    await asyncio.sleep(3)  # Delay antar kirim
                except Exception as e:
                    fail += 1
                    logger.error(f"Broadcast error untuk {psid}: {e}")

        return (
            f"BROADCAST SELESAI\n\n"
            f"Berhasil: {success} user\n"
            f"Gagal   : {fail} user\n"
            f"Pesan   : {args[:100]}..."
        )

    # ── #log {n} ───────────────────────────────────
    elif cmd == "#log":
        n = int(args) if args.isdigit() else 10
        n = min(n, 20)  # Max 20 baris via Messenger

        if not LOG_PATH.exists():
            return "File log belum ada (belum ada aktivitas)."

        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        last_lines = lines[-n:]
        log_text = "".join(last_lines)

        # Potong jika terlalu panjang untuk Messenger (max 2000 char)
        if len(log_text) > 1800:
            log_text = "...(dipotong)\n" + log_text[-1800:]

        return f"LOG TERAKHIR ({n} baris):\n\n{log_text}"

    # ── #reload ────────────────────────────────────
    elif cmd == "#reload":
        try:
            import logic.ai_engine as ai_module
            # Reload knowledge
            new_data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
            ai_module.PRODUCT_KNOWLEDGE = new_data
            ai_module.SYSTEM_PROMPT = ai_module._build_system_prompt()
            brand = new_data.get("brand", "?")
            produk_count = len(new_data.get("produk", []))
            return (
                f"Produk knowledge berhasil di-reload!\n"
                f"Brand: {brand}\n"
                f"Jumlah produk: {produk_count}\n"
                f"Sistem prompt AI sudah diperbarui."
            )
        except Exception as e:
            return f"Gagal reload: {e}"

    # ── #setpromo {teks} ───────────────────────────
    elif cmd == "#setpromo":
        if not args:
            return "Format: #setpromo {judul}|{deskripsi}|{tanggal}\nContoh: #setpromo Promo Juni|Beli 2 gratis 1|30 Juni 2026"
        try:
            import logic.ai_engine as ai_module
            data = KNOWLEDGE_PATH.read_text(encoding="utf-8")
            knowledge = json.loads(data)
            
            promo_parts = [p.strip() for p in args.split("|")]
            knowledge["promo_aktif"] = {
                "judul": promo_parts[0] if len(promo_parts) > 0 else args,
                "deskripsi": promo_parts[1] if len(promo_parts) > 1 else "",
                "berlaku_hingga": promo_parts[2] if len(promo_parts) > 2 else "",
            }
            KNOWLEDGE_PATH.write_text(
                json.dumps(knowledge, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            ai_module.PRODUCT_KNOWLEDGE = knowledge
            ai_module.SYSTEM_PROMPT = ai_module._build_system_prompt()
            return f"Promo berhasil diupdate!\nJudul: {knowledge['promo_aktif']['judul']}\nDeskripsi: {knowledge['promo_aktif']['deskripsi']}"
        except Exception as e:
            return f"Gagal update promo: {e}"

    # ── Perintah tidak dikenal ─────────────────────
    else:
        return f"Perintah '{cmd}' tidak dikenal.\nKetik #help untuk daftar perintah."
