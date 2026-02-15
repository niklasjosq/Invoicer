# Factur-X / ZUGFeRD Generator & API

This project provides both a **Streamlit Web UI** for manual invoice creation and a **FastAPI backend** for automated XML generation. Both tools produce strict Factur-X Basic Profile XML compliant with EN 16931 and XRechnung.

## Features

-   **Streamlit Web UI**: User-friendly interface for manual data entry, history persistence, XML preview, and PDF viewing.
-   **FastAPI Backend**: High-performance asynchronous API for automated invoice generation via JSON.
-   **Strict Compliance**: Generates Factur-X Basic Profile XML (`urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic`).
-   **XRechnung Ready**: Supports Project IDs (BT-18), Purchase Order IDs (BT-13), Due Dates (BT-9), and mandatory party details.

## Installation

```bash
uv sync
```

## Usage

### 1. Web UI (Streamlit)
To run the interactive web interface:
```bash
uv run streamlit run invoice_app/app.py
```

### 2. Web API (FastAPI)
To run the backend API service:
```bash
uv run uvicorn invoice_app.api:app --host 0.0.0.0 --port 8000
```
Send a `POST` request to `http://localhost:8000/generate-xml`.

### Example Request

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
    {
      "name": "Project Management",
      "qty": 10.0,
      "price": 120.0,
      "vat_percent": 19.0
    }
  ],
  "currency": "EUR"
}
```

## Project Structure

```text
Invoicer/
├── invoice_app/
│   ├── app.py            # Streamlit Web User Interface
│   ├── api.py            # FastAPI Web API
│   └── invoice_logic.py  # Shared Factur-X / ZUGFeRD generation logic
├── pyproject.toml        # Project dependencies & tool config
└── README.md             # Project documentation
```

## License

[MIT](https://choosealicense.com/licenses/mit/)
