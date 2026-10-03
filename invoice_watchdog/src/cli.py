import argparse
import sys
from src.parser import parse_invoice
from src.validator import validate_invoice
from src.ledger import store_invoice, verify_ledger

def main():
    parser = argparse.ArgumentParser(description="Invoice_WatchDog: Intelligent Invoice Extractor & Anomaly Auditor")
    parser.add_argument("--file", required=True, help="Path to invoice image or PDF")
    parser.add_argument("--db", default="invoice_watchdog.db", help="Path to SQLite database")
    parser.add_argument("--audit-only", action="store_true", help="Audit database hash-chain without adding a new file")

    args = parser.parse_args()

    # Standalone command to verify database integrity
    if args.audit_only:
        valid = verify_ledger(args.db)
        status = "✅ LEDGER VERIFIED: All records intact." if valid else "❌ TAMPER DETECTED: Hash chain broken!"
        print(status)
        return

    try:
        # Step 1: AI Vision Extraction to JSON
        invoice = parse_invoice(args.file)

        # Step 2: Deterministic Business Validation
        val_results = validate_invoice(invoice, db_path=args.db)

        # Step 3: Hash-Chained Storage
        rec_hash, chain_valid = store_invoice(invoice, db_path=args.db)

        # Step 4: Display Output Report
        print("\n" + "=" * 55)
        print("🛡️  INVOICE_WATCHDOG ANALYSIS REPORT")
        print("=" * 55)
        print(f"Supplier      : {invoice.supplier_name}")
        print(f"Invoice No    : {invoice.invoice_number}")
        print(f"Date          : {invoice.date}")
        print(f"Total Stated  : {invoice.total_amount:,.2f}")

        print("\n--- LINE ITEMS ---")
        for idx, item in enumerate(invoice.line_items, 1):
            print(f"{idx}. {item.name:<25} | Qty: {item.quantity:<4} | Unit: {item.unit_price:>8,.2f} | Total: {item.total_price:>10,.2f}")

        print("\n--- ANOMALIES & FLAGS ---")
        for flag in val_results["flags"]:
            print(flag)

        print("\n--- LEDGER STATUS ---")
        print(f"⛓  Block Hash : {rec_hash}")
        chain_label = "VERIFIED (Tamper-free)" if chain_valid else "CORRUPTED / TAMPERED"
        print(f"🔒 Integrity  : {chain_label}")
        print("=" * 55 + "\n")

    except Exception as exc:
        print(f"❌ Execution failed: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()