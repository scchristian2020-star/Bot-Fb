"""
logic/ai_engine.py
Mesin AI utama: membaca produk_knowledge.json, mendeteksi intent,
dan menghasilkan balasan natural menggunakan Gemini atau OpenAI.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  LOAD PRODUK KNOWLEDGE
# ──────────────────────────────────────────────

KNOWLEDGE_PATH = Path(__file__).parent.parent / "produk_knowledge.json"

def _load_knowledge() -> dict:
    """Load produk_knowledge.json dari disk."""
    try:
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ File produk_knowledge.json tidak ditemukan di {KNOWLEDGE_PATH}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON error di produk_knowledge.json: {e}")
        return {}

PRODUCT_KNOWLEDGE = _load_knowledge()


def _build_system_prompt() -> str:
    """
    Buat system prompt berdasarkan data dari produk_knowledge.json.
    Prompt ini dikirim sebagai konteks ke LLM setiap sesi.
    """
    brand = PRODUCT_KNOWLEDGE.get("brand", "Toko Kami")
    tagline = PRODUCT_KNOWLEDGE.get("tagline", "")
    promo = PRODUCT_KNOWLEDGE.get("promo_aktif", {})
    kebijakan = PRODUCT_KNOWLEDGE.get("kebijakan", {})
    kontak = PRODUCT_KNOWLEDGE.get("kontak_admin", {})

    # Format daftar produk
    produk_list = ""
    for p in PRODUCT_KNOWLEDGE.get("produk", []):
        produk_list += f"""
  - {p['nama']} | Harga: {p['harga']} | Stok: {p['stok']} | Garansi: {p['garansi']}
    Keunggulan: {', '.join(p.get('keunggulan', [])[:3])}"""

    promo_text = ""
    if promo:
        promo_text = f"\nPROMO AKTIF: {promo.get('judul','')} — {promo.get('deskripsi','')} (s/d {promo.get('berlaku_hingga','')})"

    system_prompt = f"""Kamu adalah AI Sales Assistant untuk brand {brand} ({tagline}).
Tugasmu adalah membantu calon pelanggan di Facebook Messenger dengan ramah, natural, dan persuasif.

PRODUK YANG TERSEDIA:{produk_list}

KEBIJAKAN:
- Pengiriman: {kebijakan.get('pengiriman', '-')}
- Pembayaran: {kebijakan.get('pembayaran', '-')}
- Retur: {kebijakan.get('retur', '-')}
{promo_text}

KONTAK ADMIN: WA {kontak.get('whatsapp', '-')} ({kontak.get('jam_operasional', '-')})

INSTRUKSI PENTING:
1. Jawab dengan bahasa Indonesia yang santai, ramah, dan natural. Jangan terlalu formal.
2. Gunakan emoji secukupnya (tidak berlebihan).
3. Jika pelanggan bertanya harga, sebutkan dengan jelas dan tawarkan promo jika ada.
4. Jika pelanggan menunjukkan minat beli, tawari untuk dihubungi admin via WhatsApp.
5. Jangan menjanjikan sesuatu yang tidak ada di data produk di atas.
6. Maksimal 3 paragraf pendek per balasan. Ringkas tapi informatif.
7. JANGAN pernah menyebut bahwa kamu adalah AI atau bot.
"""
    return system_prompt


SYSTEM_PROMPT = _build_system_prompt()


# ──────────────────────────────────────────────
#  INTENT DETECTION
# ──────────────────────────────────────────────

# Kata kunci pendeteksi intent
INTENT_KEYWORDS = {
    "LEAD_BUY": [
        "beli", "pesan", "order", "mau beli", "berminat", "minat", "mau pesan",
        "harga", "bayar", "transfer", "dp", "cod", "ongkir", "kirim", "stok",
        "available", "ready", "bisa dikirim", "cara beli", "cara order"
    ],
    "ANGRY": [
        "marah", "kesal", "kecewa", "bohong", "tipu", "scam", "penipu",
        "komplain", "complaint", "tidak puas", "kurang ajar", "brengsek",
        "jelek", "buruk", "minta refund", "kembalikan uang", "lapor"
    ],
    "HUMAN_REQUEST": [
        "minta admin", "hubungi admin", "bicara dengan manusia", "chat admin",
        "ada admin", "ada manusia", "cs manusia", "customer service", "speak to human",
        "minta cs", "call admin", "connect admin"
    ],
    "GREETING": [
        "halo", "hai", "hi", "selamat", "ola", "assalamualaikum", "halo kak",
        "permisi", "numpang tanya", "mau tanya", "nanya dulu", "boleh tanya"
    ],
}


def detect_intent(message: str) -> str:
    """
    Deteksi intent dari pesan pelanggan.
    Returns: 'LEAD_BUY' | 'ANGRY' | 'HUMAN_REQUEST' | 'GREETING' | 'GENERAL'
    """
    msg_lower = message.lower()

    # Cek setiap intent berdasarkan keyword (prioritas: ANGRY > HUMAN_REQUEST > LEAD_BUY > GREETING)
    for intent in ["ANGRY", "HUMAN_REQUEST", "LEAD_BUY", "GREETING"]:
        keywords = INTENT_KEYWORDS[intent]
        if any(kw in msg_lower for kw in keywords):
            logger.info(f"🎯 Intent terdeteksi: {intent}")
            return intent

    return "GENERAL"


def extract_whatsapp_number(message: str) -> Optional[str]:
    """
    Ekstrak nomor WhatsApp dari pesan pelanggan.
    Mendukung format: 081234567890, +6281234567890, 6281234567890,
                      0812-3456-7890, 0812 3456 7890
    """
    # Pre-clean: hapus karakter pemisah umum agar pattern bisa match
    cleaned = message.replace("-", "").replace(".", "")

    # Pattern nomor telepon Indonesia (urutan penting: lebih spesifik dulu)
    patterns = [
        r'\+62\d{9,12}',   # +6281234567890
        r'62\d{9,12}',      # 6281234567890
        r'0\d{9,12}',       # 081234567890
        r'\d{10,13}',       # Nomor mentah 10-13 digit
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            number = match.group().strip()
            # Normalisasi ke format 62xxx
            if number.startswith("+62"):
                number = "62" + number[3:]   # Hapus +62, tambah 62
            elif number.startswith("0"):
                number = "62" + number[1:]   # Ganti 0 dengan 62
            elif not number.startswith("62"):
                number = "62" + number        # Tambah 62 di depan

            # Validasi panjang akhir (10-15 digit total)
            if 10 <= len(number) <= 15:
                logger.info(f"Nomor WA terdeteksi: {number}")
                return number

    return None



# ──────────────────────────────────────────────
#  LLM INTEGRATION
# ──────────────────────────────────────────────

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()


def _call_gemini(user_message: str, history: List[Dict]) -> Optional[str]:
    """Generate balasan menggunakan Google Gemini."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel(
            model_name=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            system_instruction=SYSTEM_PROMPT
        )

        # Format history untuk Gemini
        chat_history = []
        for msg in history[:-1]:  # Exclude pesan terakhir (akan jadi user turn)
            role = "user" if msg["role"] == "user" else "model"
            chat_history.append({"role": role, "parts": [msg["message"]]})

        chat = model.start_chat(history=chat_history)
        response = chat.send_message(user_message)
        return response.text

    except Exception as e:
        logger.error(f"❌ Gemini API error: {e}")
        return None


def _call_openai(user_message: str, history: List[Dict]) -> Optional[str]:
    """Generate balasan menggunakan OpenAI GPT."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Format messages untuk OpenAI
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history[:-1]:
            messages.append({
                "role": msg["role"],
                "content": msg["message"]
            })
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"❌ OpenAI API error: {e}")
        return None


def generate_reply(user_message: str, history: Optional[List[Dict]] = None) -> str:
    """
    Generate balasan AI untuk pesan pelanggan.

    Args:
        user_message: Pesan dari pelanggan
        history: Riwayat percakapan [{'role': 'user'/'assistant', 'message': '...'}]

    Returns:
        String balasan dari AI
    """
    if history is None:
        history = []

    # Tambahkan pesan saat ini ke history untuk konteks
    full_history = history + [{"role": "user", "message": user_message}]

    logger.info(f"🤖 Generating reply via {LLM_PROVIDER.upper()}...")

    reply = None
    if LLM_PROVIDER == "gemini":
        reply = _call_gemini(user_message, full_history)
    elif LLM_PROVIDER == "openai":
        reply = _call_openai(user_message, full_history)
    else:
        logger.error(f"❌ LLM_PROVIDER tidak dikenal: {LLM_PROVIDER}")

    if not reply:
        # Fallback jika LLM gagal
        reply = (
            "Mohon maaf, saya sedang ada gangguan teknis 🙏 "
            "Silakan hubungi admin kami langsung ya! "
            f"WA: {PRODUCT_KNOWLEDGE.get('kontak_admin', {}).get('whatsapp', '-')}"
        )

    return reply


# ──────────────────────────────────────────────
#  TEMPLATE PESAN KHUSUS
# ──────────────────────────────────────────────

def get_lead_capture_message() -> str:
    """Pesan untuk meminta nomor WhatsApp pelanggan."""
    brand = PRODUCT_KNOWLEDGE.get("brand", "kami")
    return (
        f"Wah, senang sekali kakak berminat dengan produk {brand}! 🎉\n\n"
        "Supaya admin kami bisa membantu proses pemesanan lebih cepat, "
        "boleh minta nomor WhatsApp kakak? 😊\n\n"
        "Nanti admin kami yang akan follow-up langsung untuk konfirmasi stok, "
        "ongkir, dan detail pengiriman ke kakak ya! 🙏"
    )


def get_wa_received_message(wa_number: str) -> str:
    """Konfirmasi setelah nomor WA diterima."""
    return (
        f"Terima kasih kak! 🙏\n\n"
        f"Nomor WhatsApp {wa_number} sudah kami catat. "
        "Admin kami akan segera menghubungi kakak dalam waktu dekat ya! 😊\n\n"
        "Kalau ada pertanyaan lain, jangan sungkan chat kami di sini kapan saja! 🌟"
    )


def get_product_detail_message() -> str:
    """Pesan detail produk untuk dikirim via DM (dari komentar)."""
    brand = PRODUCT_KNOWLEDGE.get("brand", "Kami")
    promo = PRODUCT_KNOWLEDGE.get("promo_aktif", {})
    kontak = PRODUCT_KNOWLEDGE.get("kontak_admin", {})

    lines = [f"✨ *Produk Unggulan {brand}* ✨\n"]
    for p in PRODUCT_KNOWLEDGE.get("produk", []):
        lines.append(f"🔧 *{p['nama']}*")
        lines.append(f"   💰 Harga: {p['harga']}")
        lines.append(f"   📦 Stok: {p['stok']}")
        lines.append(f"   🛡️ Garansi: {p['garansi']}")
        lines.append(f"   ✅ {p['keunggulan'][0]}" if p.get('keunggulan') else "")
        lines.append("")

    if promo:
        lines.append(f"🎁 *{promo.get('judul','')}*: {promo.get('deskripsi','')}")
        lines.append(f"   (Berlaku s/d {promo.get('berlaku_hingga','')})\n")

    lines.append(f"📱 Order & info: WA {kontak.get('whatsapp','-')}")
    lines.append(f"🕐 {kontak.get('jam_operasional','-')}")

    return "\n".join(lines)
