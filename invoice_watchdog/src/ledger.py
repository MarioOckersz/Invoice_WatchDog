import sqlite3
import hashlib

# Genesis hash for the initial entry in an empty database
GENESIS_HASH = "0" * 64

def get_latest_hash(cursor) -> str:
    """Returns the current_hash of the newest row, or the GENESIS_HASH if empty."""
    cursor.execute("SELECT current_hash FROM invoices ORDER BY id DESC LIMIT 1;")
    row = cursor.fetchone()
    return row[0] if row else GENESIS_HASH

def store_invoice(invoice_data, db_path: str = "invoice_watchdog.db") -> tuple[str, bool]:
    """
    Saves the invoice record to SQLite linked cryptographically to the preceding row.
    """
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

    prev_hash = get_latest_hash(cursor)
    raw_json = invoice_data.model_dump_json()

    # Cryptographic block formulation: previous hash + invoice content
    payload = f"{prev_hash}:{invoice_data.supplier_name}:{invoice_data.invoice_number}:{invoice_data.total_amount}:{raw_json}"
    current_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    cursor.execute("""
        INSERT INTO invoices (supplier, invoice_number, date, total, data_json, prev_hash, current_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        invoice_data.supplier_name,
        invoice_data.invoice_number,
        invoice_data.date,
        invoice_data.total_amount,
        raw_json,
        prev_hash,
        current_hash
    ))

    conn.commit()
    conn.close()

    # Re-verify the full ledger to ensure integrity
    chain_valid = verify_ledger(db_path)
    return current_hash, chain_valid

def verify_ledger(db_path: str = "invoice_watchdog.db") -> bool:
    """
    Audits the entire table from top to bottom, verifying every SHA-256 checksum.
    Returns False if any row has been altered or deleted.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, supplier, invoice_number, total, data_json, prev_hash, current_hash FROM invoices ORDER BY id ASC;")
    records = cursor.fetchall()
    conn.close()

    expected_previous = GENESIS_HASH

    for row in records:
        _, supplier, inv_num, total, raw_json, prev_hash, stored_hash = row

        # 1. Does this record correctly point to the previous hash?
        if prev_hash != expected_previous:
            return False

        # 2. Recalculate hash of row contents
        payload = f"{prev_hash}:{supplier}:{inv_num}:{total}:{raw_json}"
        recalculated_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # 3. Does row content match the hash recorded?
        if recalculated_hash != stored_hash:
            return False

        expected_previous = stored_hash

    return True