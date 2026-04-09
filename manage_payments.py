#!/usr/bin/env python3
"""
CLI tool to manage invoice payment dates.

Scans the local directory for invoice PDFs/XMLs, merges with existing
transactions, and lets you enter payment dates interactively.
Results are saved to transactions.json (the same file the Streamlit app reads).

Usage:
    uv run python manage_payments.py              # interactive mode
    uv run python manage_payments.py --list       # list-only, no prompts
    uv run python manage_payments.py --all        # show all transactions (incl. already paid)
    uv run python manage_payments.py --dir /path  # scan a specific directory
"""

import argparse
import datetime
import json
import os
import sys

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from invoice_app.accounting_logic import extract_data_from_pdf, extract_data_from_xml_file

TRANSACTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transactions.json")


# ── data helpers ──────────────────────────────────────────────────────────

def load_transactions():
    if not os.path.exists(TRANSACTIONS_FILE):
        return []
    try:
        with open(TRANSACTIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_transactions(data):
    tmp = TRANSACTIONS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4, default=str)
    os.replace(tmp, TRANSACTIONS_FILE)


def parse_date(text):
    """Parse YYYY-MM-DD or DD.MM.YYYY, return ISO string or None."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── directory scanner ─────────────────────────────────────────────────────

def scan_directory(scan_dir):
    """Walk *scan_dir* for .pdf/.xml files, extract invoice data.
    Returns list of transaction dicts (payment_date will be None).
    """
    all_files = {}
    for root, _dirs, files in os.walk(scan_dir):
        for fname in files:
            lower = fname.lower()
            if lower.endswith((".pdf", ".xml")):
                stem = os.path.splitext(fname)[0]
                fpath = os.path.join(root, fname)
                # prefer PDF when both exist
                if stem not in all_files or lower.endswith(".pdf"):
                    all_files[stem] = fpath

    results = []
    for fpath in all_files.values():
        try:
            if fpath.lower().endswith(".pdf"):
                data = extract_data_from_pdf(fpath)
            else:
                data = extract_data_from_xml_file(fpath)
        except Exception:
            data = None
        if data and data.get("id"):
            method = data.pop("_extraction_method", None)
            conf = data.pop("_extraction_confidence", None)
            if method and method != "zugferd":
                print(f"    {os.path.basename(fpath)}: [{method}, {conf:.0%} confidence]")
            results.append(data)
    return results


# ── display helpers ───────────────────────────────────────────────────────

COL_WIDTHS = {"idx": 4, "id": 22, "date": 12, "partner": 28, "gross": 12, "paid": 12}

def header_line():
    return (
        f"{'#':>{COL_WIDTHS['idx']}}"
        f"  {'ID':<{COL_WIDTHS['id']}}"
        f"  {'Date':<{COL_WIDTHS['date']}}"
        f"  {'Partner':<{COL_WIDTHS['partner']}}"
        f"  {'Brutto':>{COL_WIDTHS['gross']}}"
        f"  {'Zahldatum':<{COL_WIDTHS['paid']}}"
    )


def format_row(idx, t):
    paid = t.get("payment_date") or "—"
    partner = (t.get("partner") or "")[:COL_WIDTHS["partner"]]
    return (
        f"{idx:>{COL_WIDTHS['idx']}}"
        f"  {(t.get('id') or '?'):<{COL_WIDTHS['id']}}"
        f"  {(t.get('date') or '—'):<{COL_WIDTHS['date']}}"
        f"  {partner:<{COL_WIDTHS['partner']}}"
        f"  {t.get('gross_amount', 0):>{COL_WIDTHS['gross']}.2f}€"
        f"  {paid:<{COL_WIDTHS['paid']}}"
    )


def print_group(title, txs, start_idx):
    """Print a titled group of transactions. Returns next index."""
    if not txs:
        return start_idx
    print(f"\n  === {title} ===")
    print(f"  {header_line()}")
    print(f"  {'—' * 96}")
    for i, t in enumerate(txs, start=start_idx):
        print(f"  {format_row(i, t)}")
    return start_idx + len(txs)


# ── main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manage invoice payment dates.")
    parser.add_argument("--dir", default=os.getenv("INVOICE_DIRECTORY", "."),
                        help="Directory to scan for invoice files (default: INVOICE_DIRECTORY or '.')")
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="List transactions only, do not prompt for dates")
    parser.add_argument("--all", action="store_true",
                        help="Show all transactions, including those with payment dates")
    parser.add_argument("--id", dest="invoice_id",
                        help="Set payment date for a single invoice by ID")
    args = parser.parse_args()

    scan_dir = os.path.abspath(args.dir)

    # 1. Load existing transactions
    transactions = load_transactions()
    existing_ids = {t["id"] for t in transactions if t.get("id")}
    print(f"\n  Loaded {len(transactions)} transactions from {os.path.basename(TRANSACTIONS_FILE)}.")

    # 2. Scan directory
    new_count = 0
    if os.path.isdir(scan_dir):
        scanned = scan_directory(scan_dir)
        for s in scanned:
            if s["id"] not in existing_ids:
                transactions.append(s)
                existing_ids.add(s["id"])
                new_count += 1
        print(f"  Scanned {scan_dir} — found {len(scanned)} invoices, {new_count} new.")
    else:
        print(f"  Warning: directory '{scan_dir}' not found, skipping scan.")

    # 3. Single-invoice mode (--id)
    if args.invoice_id:
        match = next((t for t in transactions if t.get("id") == args.invoice_id), None)
        if not match:
            print(f"\n  Invoice '{args.invoice_id}' not found.\n")
            return
        current = match.get("payment_date")
        suffix = f" [current: {current}]" if current else ""
        print(f"\n  {format_row(1, match)}")
        try:
            raw = input(f"\n  Payment date for {args.invoice_id}{suffix} (YYYY-MM-DD or DD.MM.YYYY, 'x' to clear): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.\n")
            return
        if not raw:
            print("  Skipped.\n")
            if new_count:
                save_transactions(transactions)
            return
        if raw.lower() in ("x", "clear"):
            match["payment_date"] = None
            save_transactions(transactions)
            print(f"  Cleared payment date for {args.invoice_id}.\n")
            return
        date_str = parse_date(raw)
        if not date_str:
            print(f"  Invalid date '{raw}'.\n")
            return
        match["payment_date"] = date_str
        save_transactions(transactions)
        print(f"  Saved {args.invoice_id} → {date_str}\n")
        return

    # 3. Select which transactions to show
    if args.all:
        show = transactions
    else:
        show = [t for t in transactions if not t.get("payment_date")]

    if not show:
        print("\n  All transactions already have payment dates. Use --all to see them.\n")
        # Still save if we added new ones from scan
        if new_count:
            save_transactions(transactions)
            print(f"  Saved {new_count} new transaction(s).\n")
        return

    # 4. Display, grouped by type
    einnahmen = [t for t in show if t.get("type") == "Einnahme"]
    ausgaben = [t for t in show if t.get("type") == "Ausgabe"]
    other = [t for t in show if t.get("type") not in ("Einnahme", "Ausgabe")]

    # Build ordered display list for consistent numbering
    display_list = []
    display_list.extend(einnahmen)
    display_list.extend(ausgaben)
    display_list.extend(other)

    idx = 1
    idx = print_group("Ausgangsrechnungen (Einnahmen)", einnahmen, idx)
    idx = print_group("Eingangsrechnungen (Ausgaben)", ausgaben, idx)
    idx = print_group("Nicht zugeordnet", other, idx)
    print()

    if args.list_only:
        if new_count:
            save_transactions(transactions)
            print(f"  Saved {new_count} new transaction(s).\n")
        return

    # 5. Interactive prompts
    print("  Enter payment dates (YYYY-MM-DD or DD.MM.YYYY).")
    print("  'x' to clear, Enter to skip, 'q' to quit and save.\n")

    updated = 0
    for i, t in enumerate(display_list, start=1):
        inv_id = t.get("id", "?")
        current = t.get("payment_date")
        suffix = f" [current: {current}]" if current else ""
        try:
            raw = input(f"  #{i} {inv_id}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw.lower() == "q":
            break
        if not raw or raw.lower() == "s":
            continue
        if raw.lower() in ("x", "clear"):
            t["payment_date"] = None
            updated += 1
            continue

        date_str = parse_date(raw)
        if date_str:
            t["payment_date"] = date_str
            updated += 1
        else:
            print(f"       Invalid date '{raw}', skipping.")

    # 6. Confirm and save
    total_changes = updated + new_count
    if total_changes == 0:
        print("\n  No changes to save.\n")
        return

    print(f"\n  {updated} payment date(s) entered, {new_count} new transaction(s) from scan.")
    try:
        confirm = input("  Save changes? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"
        print()

    if confirm in ("", "y", "yes", "j", "ja"):
        save_transactions(transactions)
        print(f"  Saved to {os.path.basename(TRANSACTIONS_FILE)}.\n")
    else:
        print("  Discarded.\n")


if __name__ == "__main__":
    main()
