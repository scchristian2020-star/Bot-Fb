# AI Business Agent — Facebook Messenger & Grup

Bot AI otomatis untuk bisnis di Facebook Messenger & Grup menggunakan Python, FastAPI, dan Meta Graph API v25.0.

## Fitur
- **Auto-Reply DM** — AI menjawab pertanyaan pelanggan secara natural (Gemini/GPT)
- **Lead Capture** — Deteksi minat beli & simpan nomor WhatsApp pelanggan
- **Auto-Reply Komentar** — Balas komentar + kirim DM detail produk
- **Human Handoff** — Notifikasi admin jika pelanggan marah atau minta manusia
- **Anti-Spam** — Random delay & rate limiter
- **Dashboard Admin** — Monitor leads & log aktivitas

## Struktur Folder
```
Bot_fb/
├── main.py                  # Entry point FastAPI
├── produk_knowledge.json    # Database produk (edit sesuai bisnis Anda)
├── requirements.txt
├── Procfile                 # Untuk deploy Railway/Render
├── assets/                  # Foto produk
├── database/
│   └── db_manager.py
└── logic/
    ├── ai_engine.py
    ├── messenger_handler.py
    ├── comment_handler.py
    ├── human_handoff.py
    ├── anti_spam.py
    └── activity_logger.py
```

## Setup

### 1. Clone repo
```bash
git clone https://github.com/USERNAME/NAMA-REPO.git
cd NAMA-REPO
pip install -r requirements.txt
```

### 2. Buat file `.env`
```bash
cp .env.example .env
# Edit .env dengan API key Anda
```

### 3. Jalankan lokal
```bash
python -m uvicorn main:app --port 8000 --reload
```

### 4. Test lokal
```bash
python test_bot.py
```

## Environment Variables
Lihat `.env.example` untuk panduan lengkap pengisian.

| Variable | Keterangan |
|----------|-----------|
| `FB_PAGE_ACCESS_TOKEN` | Token dari Meta Developer |
| `FB_VERIFY_TOKEN` | Token unik buatan sendiri |
| `FB_APP_SECRET` | Secret dari Meta Developer App |
| `GEMINI_API_KEY` | API key Google Gemini (gratis) |

## Deploy ke Railway
1. Push repo ini ke GitHub
2. Buka [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Set semua environment variables di Railway dashboard
4. Gunakan URL Railway sebagai webhook di Meta Developer

## Lisensi
MIT
