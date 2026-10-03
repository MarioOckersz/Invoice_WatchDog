import sqlite3
import json
from typing import Dict, Any, List

def validate_invoice(invoice_data: Any, db_path: str = "invoice_watchdog.db") -> Dict[str, Any]:
    """
    Performs pure Python deterministic checks:
    1. Line items sum vs stated grand total.
    2. Duplicate invoice number verification.
    3. Price jump detection (>15%) compared to the previous delivery.
    """
    flags: List[str] = []

    # --- Check 1: Math Verification ---
    calculated_total = sum(item.quantity * item.unit_price for item in invoice_data.line_items)
    # A tolerance threshold of 1.0 accommodates minor rounding or tax variations
    if abs(calculated_total - invoice_data.total_amount) > 1.0:
        flags.append(
            f"❌ [MATH MISMATCH]: Sum of lines ({calculated_total:,.2f}) does not match stated total ({invoice_data.total_amount:,.2f})."
        )
    else:
        flags.append("✅ [MATH CHECK]: Line items sum matches stated grand total.")

    # Connect to SQLite database to perform historical checks
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the invoices table if it doesn't exist yet
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

    # --- Check 2: Duplicate Detection ---
    cursor.execute(
        "SELECT id FROM invoices WHERE supplier = ? AND invoice_number = ?",
        (invoice_data.supplier_name, invoice_data.invoice_number)
    )
    if cursor.fetchone():
        flags.append(
            f"⚠ [DUPLICATE DETECTED]: Invoice #{invoice_data.invoice_number} from '{invoice_data.supplier_name}' has already been processed!"
        )
    else:
        flags.append("✅ [DUPLICATE CHECK]: Invoice identifier is unique.")

    # --- Check 3: Price Spike Detection (>15% jump) ---
    price_spikes = []
    for item in invoice_data.line_items:
        # Retrieve previous invoices from this specific supplier in reverse chronological order
        cursor.execute(
            "SELECT data_json FROM invoices WHERE supplier = ? ORDER BY id DESC",
            (invoice_data.supplier_name,)
        )
        history = cursor.fetchall()
        
        last_recorded_price = None
        for record in history:
            parsed_history = json.loads(record[0])
            for hist_item in parsed_history.get("line_items", []):
                # Simple case-insensitive name match
                if hist_item["name"].strip().lower() == item.name.strip().lower():
                    last_recorded_price = hist_item["unit_price"]
                    break
            if last_recorded_price is not None:
                break

        if last_recorded_price and last_recorded_price > 0:
            percentage_jump = ((item.unit_price - last_recorded_price) / last_recorded_price) * 100
            if percentage_jump > 15.0:
                price_spikes.append(
                    f"⚠ [PRICE SPIKE]: '{item.name}' jumped {percentage_jump:.1f}% "
                    f"(Current: {item.unit_price:,.2f} | Last: {last_recorded_price:,.2f})"
                )

    conn.close()

    if price_spikes:
        flags.extend(price_spikes)
    else:
        flags.append("✅ [PRICE CHECK]: No abnormal price spikes (>15%) found.")

    return {
        "calculated_total": calculated_total,
        "flags": flags
    }