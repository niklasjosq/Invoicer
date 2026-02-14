# ZUGFeRD Invoice Generator

A Python Streamlit application that generates ZUGFeRD (EN 16931) compliant electronic invoices. This tool allows you to input invoice details, generates the required XML structure, creates a visual PDF, and embeds the XML into the PDF to create a valid PDF/A-3 ZUGFeRD invoice.

PDF and XML validator:
https://www.xrechnungs.de/xrechnung-validator-online

## Features

- **Tabbed Interface**: Organized into "Input Data", "XML Preview", and "PDF Preview" tabs.
- **Enhanced Data Entry**:
  - **Multi-line Address Inputs**: Easily paste full addresses for Sender and Recipient.
  - **Smart Line Items**: Automatic calculation of Total, Tax, and Gross values with support for **Manual Overrides**.
- **EN 16931 Compliance**: Generates XML strictly following the European e-invoicing standard using `drafthorse`.
- **Editable XML & Sync**:
  - **View/Edit**: Modify the generated XML code directly.
  - **Upload**: Upload existing ZUGFeRD XML files.
  - **Auto-Sync**: Automatically updates the PDF when XML changes or is uploaded.
- **Visual PDF Generation**: Creates professional-looking PDF invoices using `fpdf2`.
- **Hybrid Invoice Creation**: Combines the visual PDF and the machine-readable XML into a single ZUGFeRD PDF/A-3 file.
- **Utilities**:
  - **Clear Settings**: Reset all inputs to defaults with one click.
  - **Invoice Counter**: Auto-incrementing invoice numbers (e.g., `INV-2026-001`).

## Tech Stack

- **[Streamlit](https://streamlit.io/)**: Frontend UI and layout.
- **[drafthorse](https://github.com/pretix/drafthorse)**: ZUGFeRD/Factur-X XML generation and PDF attachment.
- **[fpdf2](https://py-pdf.github.io/fpdf2/)**: Visual PDF generation.
- **[streamlit-pdf-viewer](https://pypi.org/project/streamlit-pdf-viewer/)**: PDF rendering in the browser.
- **[uv](https://github.com/astral-sh/uv)**: Fast Python package manager.

## Installation

This project uses `uv` for dependency management.

1.  **Clone the repository** (if applicable) and navigate to the project folder:
    ```bash
    cd Invoicer
    ```

2.  **Install dependencies**:
    ```bash
    uv sync
    ```
    Or manually:
    ```bash
    uv add streamlit drafthorse fpdf2 streamlit-pdf-viewer
    ```

## Usage

1.  **Run the application**:
    ```bash
    uv run streamlit run invoice_app/app.py
    ```

2.  **Open your browser**: The app will typically be available at `http://localhost:8501`.

3.  **Create an Invoice**:
    - **Input Data Tab**:
        - Paste Sender and Recipient details (Name + Address).
        - Add line items (Quantity, Price/Hour). Totals are calculated automatically, but you can override them manually if needed.
        - Click **"Generate Invoice"**.
    - **XML Preview Tab**:
        - View or Edit the generated XML.
        - Upload an external XML file to replace the content.
        - Click **"Sync to PDF"** to update the PDF with your changes.
    - **PDF Preview Tab**:
        - View the final ZUGFeRD PDF.
        - Download using the button provided.

## Project Structure

```text
Invoicer/
├── invoice_app/
│   ├── app.py            # Main Streamlit application entry point
│   └── invoice_logic.py  # Core logic for XML and PDF generation
├── pyproject.toml        # Project dependencies and configuration
└── README.md             # Project documentation
```

## License

[MIT](https://choosealicense.com/licenses/mit/)
