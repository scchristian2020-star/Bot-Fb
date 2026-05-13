"""
main.py — AI Business Agent untuk Facebook Messenger & Grup
Entry point FastAPI: menangani Webhook Meta, routing pesan,
dan menyediakan dashboard admin sederhana.

Jalankan: uvicorn main:app --reload --port 8000
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

# ── Load .env sebelum import lainnya ──
load_dotenv()

# ── Setup Logging ──
from logic.activity_logger import setup_logging, log_event
setup_logging()
logger = logging.getLogger(__name__)

# ── Import handlers ──
from database.db_manager import init_db, get_all_leads, get_customer
from logic.messenger_handler import handle_dm
from logic.comment_handler import handle_comment

# ── Konfigurasi ──
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"


# ──────────────────────────────────────────────
#  LIFESPAN — Startup & Shutdown
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Jalankan task startup dan cleanup shutdown."""
    logger.info("🚀 AI Business Agent starting up...")
    init_db()
    log_event("APP_STARTED", f"Port: {APP_PORT} | Debug: {DEBUG}")

    # Validasi konfigurasi wajib — cek kosong DAN nilai placeholder
    PLACEHOLDERS = {
        "your_page_access_token_here", "your_app_secret_here",
        "your_gemini_api_key_here", "your_openai_api_key_here",
        "numeric_psid_akun_facebook_admin", "your_numeric_page_id_here",
        "buat_token_unik_sendiri_misal_lazaro2025bot",
    }

    def _is_unset(val: str) -> bool:
        return not val or val.strip() in PLACEHOLDERS

    missing = []
    for var in ["FB_PAGE_ACCESS_TOKEN", "FB_VERIFY_TOKEN", "FB_APP_SECRET", "FB_PAGE_ID"]:
        if _is_unset(os.getenv(var, "")):
            missing.append(var)

    if missing:
        logger.warning(f"⚠️  PERLU DIISI di .env: {', '.join(missing)}")
        logger.warning("⚠️  Bot akan berjalan tapi TIDAK BISA menerima webhook dari Meta!")
    else:
        logger.info("✅ Semua konfigurasi Meta sudah lengkap.")

    llm = os.getenv("LLM_PROVIDER", "gemini")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if llm == "gemini" and _is_unset(gemini_key):
        logger.warning("⚠️  GEMINI_API_KEY belum diisi di .env — AI tidak akan berfungsi!")
    elif llm == "openai" and _is_unset(openai_key):
        logger.warning("⚠️  OPENAI_API_KEY belum diisi di .env — AI tidak akan berfungsi!")
    else:
        logger.info(f"✅ LLM Provider: {llm.upper()} siap.")

    yield  # ← Aplikasi berjalan

    logger.info("🛑 AI Business Agent shutting down...")
    log_event("APP_STOPPED")


# ──────────────────────────────────────────────
#  FASTAPI APP
# ──────────────────────────────────────────────

app = FastAPI(
    title="AI Business Agent",
    description="Bot AI untuk Facebook Messenger & Grup",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if DEBUG else None,  # Sembunyikan docs di produksi
)


# ──────────────────────────────────────────────
#  WEBHOOK VERIFICATION (GET)
# ──────────────────────────────────────────────

@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Endpoint verifikasi webhook dari Meta.
    Meta akan mengirim GET request dengan parameter ini saat setup.
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    token_preview = token[:6] if token else "(kosong)"
    logger.info(f"🔐 Webhook verification request | mode={mode} | token={token_preview}...")

    if mode == "subscribe" and token == FB_VERIFY_TOKEN:
        logger.info("✅ Webhook verified successfully!")
        log_event("WEBHOOK_VERIFIED")
        return PlainTextResponse(content=challenge)

    logger.warning("❌ Webhook verification FAILED — token tidak cocok!")
    raise HTTPException(status_code=403, detail="Verification failed")


# ──────────────────────────────────────────────
#  WEBHOOK HANDLER (POST)
# ──────────────────────────────────────────────

def _verify_signature(request_body: bytes, signature_header: str) -> bool:
    """Verifikasi signature X-Hub-Signature-256 dari Meta untuk keamanan."""
    if not FB_APP_SECRET or not signature_header:
        return True  # Skip jika belum dikonfigurasi (development)

    if not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        FB_APP_SECRET.encode("utf-8"),
        msg=request_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint utama penerima event dari Meta (pesan, komentar, dll).
    Semua pemrosesan dijalankan di background agar response cepat (< 5 detik).
    """
    # Ambil body dan verifikasi signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_signature(body, signature):
        logger.warning("❌ Signature tidak valid! Request ditolak.")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # ── Hanya proses event dari 'page' ──
    if data.get("object") != "page":
        return JSONResponse({"status": "ignored"})

    for entry in data.get("entry", []):
        # ── MESSAGING (DM / Messenger) ──
        for messaging_event in entry.get("messaging", []):
            sender_id = messaging_event.get("sender", {}).get("id")
            page_id = messaging_event.get("recipient", {}).get("id")

            # Skip pesan dari page itu sendiri
            if sender_id == os.getenv("FB_PAGE_ID"):
                continue

            if "message" in messaging_event:
                msg = messaging_event["message"]
                # Skip echo (pesan yang dikirim page)
                if msg.get("is_echo"):
                    continue

                text = msg.get("text", "")
                if text and sender_id:
                    background_tasks.add_task(handle_dm, sender_id, text)

            elif "postback" in messaging_event:
                # Tangani postback dari quick replies atau tombol
                payload = messaging_event["postback"].get("payload", "")
                if sender_id and payload:
                    background_tasks.add_task(
                        handle_dm, sender_id, f"[POSTBACK] {payload}"
                    )

        # ── CHANGES (Komentar di Post/Grup) ──
        for change in entry.get("changes", []):
            value = change.get("value", {})
            field = change.get("field")

            if field == "feed" and value.get("item") == "comment":
                comment_id = value.get("comment_id", "")
                commenter_psid = value.get("sender_id", "")
                comment_text = value.get("message", "")
                post_id = value.get("post_id", "")

                # Hanya proses komentar yang dibuat (bukan edit/hapus)
                if value.get("verb") == "add" and comment_id and commenter_psid:
                    background_tasks.add_task(
                        handle_comment,
                        comment_id,
                        commenter_psid,
                        comment_text,
                        post_id
                    )

    return JSONResponse({"status": "ok"})


# ──────────────────────────────────────────────
#  ADMIN DASHBOARD (sederhana via HTML)
# ──────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    """
    Dashboard admin sederhana untuk melihat leads dan statistik.
    Akses: http://localhost:8000/admin
    """
    leads = get_all_leads()
    log_path = Path(__file__).parent / os.getenv("LOG_FILE", "activity_log.txt")

    # Baca 50 baris log terakhir
    recent_logs = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            recent_logs = lines[-50:]

    leads_html = ""
    for lead in leads:
        status_color = {
            "lead": "#22c55e",
            "handoff": "#ef4444",
            "customer": "#3b82f6",
            "prospect": "#f59e0b"
        }.get(lead.get("status", "prospect"), "#6b7280")

        leads_html += f"""
        <tr>
            <td>{lead.get('id','')}</td>
            <td><code>{lead.get('fb_psid','')[:12]}...</code></td>
            <td>{lead.get('nama') or '-'}</td>
            <td>{lead.get('whatsapp') or '-'}</td>
            <td><span style="color:{status_color};font-weight:600">{lead.get('status','').upper()}</span></td>
            <td>{lead.get('source','')}</td>
            <td style="font-size:11px">{lead.get('created_at','')}</td>
        </tr>"""

    logs_html = "".join(
        f'<div class="log-line">{line.rstrip()}</div>'
        for line in reversed(recent_logs)
    )

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard — AI Business Agent</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #1d4ed8, #7c3aed);
            padding: 20px 30px;
            display: flex;
            align-items: center;
            gap: 15px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .header h1 {{ font-size: 1.4rem; font-weight: 700; }}
        .header .badge {{
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
        }}
        .container {{ padding: 30px; max-width: 1400px; margin: 0 auto; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
        }}
        .stat-card .label {{ color: #94a3b8; font-size: 13px; margin-bottom: 8px; }}
        .stat-card .value {{ font-size: 2rem; font-weight: 700; color: #60a5fa; }}
        .section-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 15px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 12px;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 25px;
        }}
        .card-header {{
            padding: 15px 20px;
            border-bottom: 1px solid #334155;
            font-weight: 600;
        }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #1e293b;
            font-size: 13px;
        }}
        th {{ background: #0f172a; color: #64748b; font-weight: 600; font-size: 11px; text-transform: uppercase; }}
        tr:hover td {{ background: rgba(255,255,255,0.03); }}
        .log-container {{
            background: #0a0f1e;
            border: 1px solid #1e293b;
            border-radius: 8px;
            padding: 15px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
        }}
        .log-line {{
            font-size: 11px;
            color: #4ade80;
            padding: 2px 0;
            border-bottom: 1px solid rgba(255,255,255,0.03);
        }}
        .refresh-btn {{
            background: #3b82f6;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            margin-left: auto;
        }}
        .refresh-btn:hover {{ background: #2563eb; }}
        .timestamp {{ color: #94a3b8; font-size: 12px; margin-top: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🤖 AI Business Agent</h1>
            <div class="timestamp">Dashboard Admin · {datetime.now().strftime('%d %b %Y, %H:%M:%S')}</div>
        </div>
        <span class="badge">🟢 Online</span>
        <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>
    </div>

    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Leads</div>
                <div class="value">{len(leads)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Status Lead</div>
                <div class="value" style="color:#22c55e">{sum(1 for l in leads if l.get('status')=='lead')}</div>
            </div>
            <div class="stat-card">
                <div class="label">Perlu Handoff</div>
                <div class="value" style="color:#ef4444">{sum(1 for l in leads if l.get('status')=='handoff')}</div>
            </div>
            <div class="stat-card">
                <div class="label">Sudah Beli</div>
                <div class="value" style="color:#a78bfa">{sum(1 for l in leads if l.get('status')=='customer')}</div>
            </div>
        </div>

        <p class="section-title">📋 Data Pelanggan & Leads</p>
        <div class="card">
            <div class="card-header">Leads Terbaru</div>
            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>PSID</th><th>Nama</th>
                        <th>WhatsApp</th><th>Status</th><th>Sumber</th><th>Waktu</th>
                    </tr>
                </thead>
                <tbody>
                    {leads_html if leads_html else '<tr><td colspan="7" style="text-align:center;color:#64748b;padding:30px">Belum ada data lead</td></tr>'}
                </tbody>
            </table>
        </div>

        <p class="section-title">📝 Log Aktivitas Terbaru (50 baris terakhir)</p>
        <div class="log-container">
            {logs_html if logs_html else '<div class="log-line" style="color:#64748b">Log kosong — bot belum menerima pesan.</div>'}
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ──────────────────────────────────────────────
#  API ENDPOINTS TAMBAHAN
# ──────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint untuk monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "llm_provider": os.getenv("LLM_PROVIDER", "gemini")
    }


@app.get("/api/leads")
async def get_leads_api():
    """API endpoint untuk mengambil semua leads (JSON)."""
    leads = get_all_leads()
    return {"total": len(leads), "leads": leads}


@app.post("/api/handoff/resume/{psid}")
async def resume_handoff_api(psid: str, background_tasks: BackgroundTasks):
    """
    API untuk menonaktifkan handoff dari luar (misal tombol di dashboard).
    POST /api/handoff/resume/{psid}
    """
    from logic.human_handoff import deactivate_handoff
    background_tasks.add_task(deactivate_handoff, psid)
    return {"status": "ok", "message": f"Handoff untuk {psid} sedang dinonaktifkan..."}


# ──────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=APP_PORT,
        reload=DEBUG,
        log_level="info"
    )
