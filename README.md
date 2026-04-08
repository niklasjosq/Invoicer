# Factur-X / ZUGFeRD Invoice Manager

Streamlit-based invoice management with ZUGFeRD/Factur-X PDF generation, ELSTER UStVA/EÜR tax reporting, and a FastAPI backend for automated XML generation.

## Features

- **Invoice Generation**: Create Factur-X Basic Profile invoices (EN 16931, XRechnung-ready) with embedded ZUGFeRD XML
- **Accounting / Tax Reporting**: UStVA generation (monthly or quarterly) with ELSTER XML export, EÜR annual overview
- **Incoming Invoices**: Upload ZUGFeRD PDFs or manually enter non-ZUGFeRD invoices, auto-categorize by ELSTER Kennzahlen
- **Payment Tracking**: CLI tool to scan invoices on disk and assign payment dates, or manage directly in the UI
- **History & Prefill**: Sender/recipient/footer templates with one-click prefill across invoice creation and tax forms
- **FastAPI Backend**: REST API for automated invoice XML generation

## Installation

```bash
uv sync
```

## Usage

### 1. Web UI (Streamlit)
```bash
uv run streamlit run invoice_app/app.py
```

Tabs:
- **Input Data** -- Create outgoing invoices (ZUGFeRD PDF with embedded XML)
- **XML / PDF Preview** -- Review generated XML and PDF before download
- **Scanner** -- Scan a directory for invoice PDFs/XMLs and import into transactions
- **UStVA** -- Monthly or quarterly Umsatzsteuervoranmeldung with ELSTER XML download
- **EÜR** -- Annual income/expense overview

### 2. Payment Date Manager (CLI)
```bash
uv run python manage_payments.py                # interactive mode
uv run python manage_payments.py --list         # list invoices missing payment dates
uv run python manage_payments.py --all          # show all transactions
uv run python manage_payments.py --id INV-001   # set/clear date for a single invoice
uv run python manage_payments.py --dir /path    # scan a specific directory
```
Writes directly to `transactions.json` -- the Streamlit app picks up changes on next load.

### 3. Web API (FastAPI)
```bash
uv run uvicorn invoice_app.api:app --host 0.0.0.0 --port 8000
```

POST to `/generate-xml`:
```json
{
  "id": "INV-2026-001",
  "issue_date": "2026-02-14",
  "seller": {
    "name": "My Consulting GmbH",
    "address_lines": ["Main Street 1", "12345 Berlin"],
    "tax_id": "DE123456789"
  },
  "buyer": {
    "name": "Client Corp",
    "address_lines": ["Second Street 2", "80331 Munich"],
    "customer_id": "CUST-99"
  },
  "items": [
    { "name": "Project Management", "qty": 10.0, "price": 120.0, "vat_percent": 19.0 }
  ],
  "currency": "EUR"
}
```

## Project Structure

```text
Invoicer/
├── invoice_app/
│   ├── app.py              # Streamlit Web UI (invoices, scanner, UStVA, EÜR)
│   ├── api.py              # FastAPI REST API
│   ├── invoice_logic.py    # Factur-X / ZUGFeRD PDF + XML generation
│   └── accounting_logic.py # UStVA / EÜR calculation, ELSTER XML, invoice extraction
├── manage_payments.py      # CLI tool for payment date management
├── transactions.json       # Invoice & payment data (gitignored)
├── invoice_history.json    # Sender/recipient/footer templates (gitignored)
├── pyproject.toml          # Dependencies & tool config
└── README.md
```

## License

[MIT](https://choosealicense.com/licenses/mit/)
