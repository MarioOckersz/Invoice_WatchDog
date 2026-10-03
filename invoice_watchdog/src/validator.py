import sqlite3
import json
from typing import Dict, Any, List

def validate_invoice(invoice_data: Any, db_path: str = "invoice_watchdog.db") -> Dict[str, Any]:
    flags: List[str] = []

    # Safe arithmetic extraction (default to 0.0 if missing/None)
    stated_total = invoice_data.total_amount or 0.0
    tax = invoice_data.tax or 0.0
    discount = invoice_data.discount or 0.0

    # 1. Line Items Arithmetic
    calculated_lines_sum = sum(
        (item.quantity or 0.0) * (item.unit_price or 0.0) 
        for item in invoice_data.line_items
    )

    # Check against subtotal or grand total
    expected_grand_total = calculated_lines_sum + tax - discount

    if abs(expected_grand_total - stated_total) > 1.0:
        flags.append(
            f"❌ [MATH MISMATCH]: Lines sum + tax - discount ({expected_grand_total:,.2f}) "
            f"does not match stated total ({stated_total:,.2f})."
        )
    else:
        flags.append("✅ [MATH CHECK]: Line items and tax balance perfectly.")

    # 2. Database Checks (Duplicates & Historical Prices)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT,
            invoice_number TEXT,
            date TEXT,
            total REAL,
            data_json TEXT,
            prev_hash TEXT,
            current_hash TEXT
        )
    """)
    conn.commit()

    # Duplicate check
    supplier = invoice_data.supplier_name or "UNKNOWN_SUPPLIER"
    inv_num = invoice_data.invoice_number or "UNKNOWN_NUMBER"

    cursor.execute(
        "SELECT id FROM invoices WHERE supplier = ? AND invoice_number = ?",
        (supplier, inv_num)
    )
    if cursor.fetchone():
        flags.append(f"⚠ [DUPLICATE DETECTED]: Invoice #{inv_num} from '{supplier}' already exists.")
    else:
        flags.append("✅ [DUPLICATE CHECK]: Invoice identifier is unique.")

    # Price spike check (>15%)
    for item in invoice_data.line_items:
        if not item.unit_price:
            continue

        cursor.execute(
            "SELECT data_json FROM invoices WHERE supplier = ? ORDER BY id DESC",
            (supplier,)
        )
        history = cursor.fetchall()
        last_price = None

        for record in history:
            parsed_history = json.loads(record[0])
            for hist_item in parsed_history.get("line_items", []):
                if hist_item.get("name", "").strip().lower() == item.name.strip().lower():
                    last_price = hist_item.get("unit_price")
                    break
            if last_price is not None:
                break

        if last_price and last_price > 0:
            jump = ((item.unit_price - last_price) / last_price) * 100
            if jump > 15.0:
                flags.append(
                    f"⚠ [PRICE SPIKE]: '{item.name}' rose {jump:.1f}% "
                    f"(Current: {item.unit_price:,.2f} | Prior: {last_price:,.2f})"
                )

    conn.close()

    return {
        "calculated_total": calculated_lines_sum,
        "flags": flags
    }