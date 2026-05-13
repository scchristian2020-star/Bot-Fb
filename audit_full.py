"""
audit_full.py — Audit menyeluruh semua komponen bot
Jalankan: python audit_full.py
"""
import sys
import json
import asyncio
import traceback
from pathlib import Path

PASS = 0
FAIL = 0

def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")

# ─────────────────────────────────────────────
#  1. JSON Knowledge
# ─────────────────────────────────────────────
section("1. produk_knowledge.json")
try:
    data = json.loads(Path("produk_knowledge.json").read_text(encoding="utf-8"))
    produk = data.get("produk", [])
    check("File bisa dibaca", True)
    check("Ada field 'brand'", bool(data.get("brand")), data.get("brand","KOSONG"))
    check("Ada minimal 1 produk", len(produk) >= 1, str(len(produk)))
    for p in produk:
        check(f"Produk '{p.get('nama','?')}' punya harga+stok",
              bool(p.get("harga")) and bool(p.get("stok")))
    check("Ada field 'kontak_admin'", bool(data.get("kontak_admin")))
    check("Ada field 'kebijakan'", bool(data.get("kebijakan")))
except Exception as e:
    check("JSON valid", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  2. Database
# ─────────────────────────────────────────────
section("2. Database SQLite")
try:
    from database.db_manager import (
        init_db, upsert_customer, get_customer, get_all_leads,
        save_message, get_history, clear_history,
        set_handoff, is_handoff_active
    )
    init_db()
    check("init_db() berhasil", True)

    upsert_customer("AUDIT001", nama="Audit User", status="prospect", source="messenger")
    c = get_customer("AUDIT001")
    check("upsert_customer + get_customer", c is not None and c.get("nama") == "Audit User")

    save_message("AUDIT001", "user", "halo ini test")
    save_message("AUDIT001", "assistant", "balasan test")
    hist = get_history("AUDIT001")
    check("save_message + get_history", len(hist) == 2, f"len={len(hist)}")

    hist2 = get_history("AUDIT001", limit=1)
    check("get_history dengan limit", len(hist2) == 1)

    clear_history("AUDIT001")
    hist3 = get_history("AUDIT001")
    check("clear_history bersihkan history", len(hist3) == 0)

    upsert_customer("AUDIT001", whatsapp="62811111111", status="lead")
    leads = get_all_leads()
    check("get_all_leads returns lead dengan WA", len(leads) >= 1)

    set_handoff("AUDIT001", active=True, reason="TEST")
    check("set_handoff aktif", is_handoff_active("AUDIT001") == True)

    set_handoff("AUDIT001", active=False)
    check("set_handoff nonaktif", is_handoff_active("AUDIT001") == False)

    # Edge case: PSID tidak ada
    none_c = get_customer("NONEXISTENT_PSID_999")
    check("get_customer PSID tidak ada -> None", none_c is None)

    # upsert dua kali (update)
    upsert_customer("AUDIT001", nama="Updated Name")
    c2 = get_customer("AUDIT001")
    check("upsert kedua kali (update) berhasil", c2.get("nama") == "Updated Name")

except Exception as e:
    check("Database error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  3. Intent Detection
# ─────────────────────────────────────────────
section("3. Intent Detection")
try:
    from logic.ai_engine import detect_intent, extract_whatsapp_number

    test_cases = [
        ("mau beli mesin las MMA 120", "LEAD_BUY"),
        ("berapa harga produknya?", "LEAD_BUY"),
        ("ada stok tidak?", "LEAD_BUY"),
        ("cara order gimana?", "LEAD_BUY"),
        ("ini penipuan saya kecewa!", "ANGRY"),
        ("saya mau komplain produk rusak", "ANGRY"),
        ("minta refund uang saya", "ANGRY"),
        ("minta admin manusia dong", "HUMAN_REQUEST"),
        ("ada customer service?", "HUMAN_REQUEST"),
        ("halo selamat pagi", "GREETING"),
        ("hai kak numpang tanya", "GREETING"),
        ("apa kabar hari ini", "GENERAL"),
    ]

    intent_pass = 0
    for msg, expected in test_cases:
        got = detect_intent(msg)
        ok = got == expected
        if ok:
            intent_pass += 1
        check(f'"{msg[:35]}"', ok, f"expected={expected}, got={got}")

    check(f"Total intent accuracy ({intent_pass}/{len(test_cases)})",
          intent_pass == len(test_cases))

except Exception as e:
    check("Intent detection error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  4. WA Number Extraction
# ─────────────────────────────────────────────
section("4. WhatsApp Number Extraction")
try:
    from logic.ai_engine import extract_whatsapp_number

    wa_cases = [
        ("nomor saya 081234567890", "6281234567890"),
        ("wa: +6281234567890", "6281234567890"),
        ("hubungi 6281234567890 ya", "6281234567890"),
        ("0812-3456-7890", "6281234567890"),  # dengan dash
        ("tidak ada nomor di sini", None),
        ("hubungi saya", None),
    ]

    for msg, expected in wa_cases:
        got = extract_whatsapp_number(msg)
        check(f'"{msg[:30]}"', got == expected, f"expected={expected}, got={got}")

except Exception as e:
    check("WA extraction error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  5. Anti-Spam / Rate Limiter
# ─────────────────────────────────────────────
section("5. Anti-Spam & Rate Limiter")
try:
    from logic.anti_spam import (
        check_rate_limit, get_message_count,
        random_greeting, random_wait, random_closing,
        get_random_delay_seconds
    )

    # Rate limiter: 10 pesan pertama harus OK
    for i in range(10):
        check_rate_limit("RATE_TEST_USER")

    # Pesan ke-11 harus ditolak
    result_11 = check_rate_limit("RATE_TEST_USER")
    check("Rate limit reject setelah 10 pesan", result_11 == False)

    count = get_message_count("RATE_TEST_USER")
    check(f"get_message_count returns 10", count == 10, str(count))

    # User berbeda tidak kena limit
    fresh = check_rate_limit("FRESH_USER_999")
    check("User baru tidak kena limit", fresh == True)

    # Humanizer tidak kosong
    greet = random_greeting()
    wait_msg = random_wait()
    close = random_closing()
    check("random_greeting() tidak kosong", len(greet) > 0)
    check("random_wait() tidak kosong", len(wait_msg) > 0)
    check("random_closing() tidak kosong", len(close) > 0)

    # Delay dalam range
    d = get_random_delay_seconds(10, 30)
    check(f"get_random_delay 10-30: {d:.1f}s", 10 <= d <= 30)

except Exception as e:
    check("Anti-spam error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  6. Admin Commands
# ─────────────────────────────────────────────
section("6. Admin Command System")
try:
    import os
    os.environ["ADMIN_FB_PSID"] = "ADMIN_AUDIT_001"

    from logic.admin_commands import (
        is_admin, is_admin_command, is_blocked, handle_admin_command
    )

    check("is_admin valid PSID", is_admin("ADMIN_AUDIT_001") == True)
    check("is_admin invalid PSID", is_admin("RANDOM_123") == False)
    check("is_admin_command '#help'", is_admin_command("#help") == True)
    check("is_admin_command 'halo'", is_admin_command("halo") == False)
    check("is_admin_command '' (kosong)", is_admin_command("") == False)

    async def run_cmds():
        cmds = ["#help", "#status", "#stats", "#leads", "#reload",
                "#info NONEXISTENT", "#log 3", "#unknown_cmd"]
        results = []
        for cmd in cmds:
            try:
                r = await handle_admin_command("ADMIN_AUDIT_001", cmd)
                results.append((cmd, True, len(r)))
            except Exception as e:
                results.append((cmd, False, str(e)))
        return results

    results = asyncio.run(run_cmds())
    for cmd, ok, detail in results:
        check(f"handle_admin_command('{cmd}')", ok, str(detail))

except Exception as e:
    check("Admin commands error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  7. AI Engine Build
# ─────────────────────────────────────────────
section("7. AI Engine System Prompt")
try:
    from logic.ai_engine import SYSTEM_PROMPT, PRODUCT_KNOWLEDGE, _build_system_prompt

    check("PRODUCT_KNOWLEDGE loaded", bool(PRODUCT_KNOWLEDGE))
    check("SYSTEM_PROMPT tidak kosong", len(SYSTEM_PROMPT) > 100,
          f"len={len(SYSTEM_PROMPT)}")
    check("SYSTEM_PROMPT mengandung nama brand",
          PRODUCT_KNOWLEDGE.get("brand","") in SYSTEM_PROMPT)
    check("SYSTEM_PROMPT mengandung harga produk",
          any(p.get("harga","") in SYSTEM_PROMPT
              for p in PRODUCT_KNOWLEDGE.get("produk",[])))

    rebuilt = _build_system_prompt()
    check("_build_system_prompt() bisa dipanggil ulang", len(rebuilt) > 100)

except Exception as e:
    check("AI engine error", False, str(e))
    traceback.print_exc()

# ─────────────────────────────────────────────
#  HASIL AKHIR
# ─────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'='*55}")
print(f"  HASIL AUDIT FINAL")
print(f"{'='*55}")
print(f"  LULUS  : {PASS}/{total}")
print(f"  GAGAL  : {FAIL}/{total}")
print()

if FAIL == 0:
    print("  STATUS: SIAP PRODUKSI")
else:
    print(f"  STATUS: ADA {FAIL} MASALAH — perbaiki sebelum deploy")

print(f"{'='*55}")
sys.exit(0 if FAIL == 0 else 1)
