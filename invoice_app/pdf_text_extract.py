"""
Text-based PDF invoice extraction for plain (non-ZUGFeRD) PDFs.

Three-tier fallback:
  1. ZUGFeRD XML (handled in accounting_logic.py, not here)
  2. pypdf text extraction + regex parsing (this module)
  3. Claude API structured extraction (this module, optional)
"""

import json
import os
import re
from io import BytesIO

from pypdf import PdfReader


# ---------------------------------------------------------------------------
# Tier 2: Text extraction + regex parsing
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> str | None:
    """Extract text from all pages of a PDF using pypdf. Returns None for image-only PDFs."""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        full = "\n".join(parts).strip()
        return full if full else None
    except Exception:
        return None


def _parse_german_number(s: str) -> float | None:
    """Parse a German-format number (1.234,56) or English (1,234.56) into float."""
    s = s.strip().replace(" ", "")
    # Remove currency symbols
    s = s.replace("€", "").replace("EUR", "").strip()
    if not s:
        return None
    # German format: dots as thousands separator, comma as decimal
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # German: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            # English: 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        # Could be German decimal: 42,50
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_german_date(s: str) -> str | None:
    """Parse DD.MM.YYYY or DD/MM/YYYY into YYYY-MM-DD. Also handles YYYY-MM-DD passthrough."""
    s = s.strip()
    # Already ISO
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    # DD.MM.YYYY or DD/MM/YYYY
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # DD.MM.YY
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{2})$", s)
    if m:
        year = int(m.group(3))
        year += 2000 if year < 80 else 1900
        return f"{year}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


# Amount patterns: label followed by an amount
_AMOUNT_PATTERNS = {
    "net": [
        r"Netto(?:betrag|summe)?[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Zwischensumme[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Summe\s+netto[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Net(?:\s+amount)?[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Subtotal[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
    ],
    "tax": [
        r"(?:MwSt|Mwst|USt|Umsatzsteuer)[\s.]*(?:\d+\s*%)?[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"(?:VAT|Tax)[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Steuer(?:betrag)?[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
    ],
    "gross": [
        r"(?:Brutto(?:betrag)?|Gesamtbetrag|Rechnungsbetrag|Zahlbetrag|Endbetrag|Fälliger\s+Betrag)[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"(?:Total|Grand\s+Total|Amount\s+Due)[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
        r"Gesamt[\s:]*([0-9.,]+)\s*(?:€|EUR)?",
    ],
}


def parse_invoice_text_regex(text: str) -> tuple[dict | None, float]:
    """
    Parse German invoice text with regex patterns.
    Returns (data_dict | None, confidence 0.0-1.0).
    """
    result: dict = {}
    fields_found = 0

    # --- Invoice number ---
    for pattern in [
        r"Rechnungs?(?:nummer|nr\.?)[\s:]*(.+?)(?:\n|$)",
        r"Rechnung\s+(?:Nr\.?|Nummer)[\s:]*(.+?)(?:\n|$)",
        r"Re\.?\s*-?\s*Nr\.?[\s:]*(.+?)(?:\n|$)",
        r"Invoice\s*(?:No\.?|Number|#)[\s:]*(.+?)(?:\n|$)",
        r"Beleg(?:nummer|nr\.?)[\s:]*(.+?)(?:\n|$)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result["id"] = m.group(1).strip()
            fields_found += 1
            break

    # --- Invoice date ---
    for pattern in [
        r"Rechnungsdatum[\s:]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"Invoice\s*Date[\s:]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"Datum[\s:]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"Date[\s:]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"Rechnungsdatum[\s:]*(\d{4}-\d{2}-\d{2})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            parsed = _parse_german_date(m.group(1))
            if parsed:
                result["date"] = parsed
                fields_found += 1
                break

    # --- VAT ID ---
    m = re.search(r"USt[\s.-]*Id[\s.-]*(?:Nr\.?)[\s:]*([A-Z]{2}\s*\d[\d\s]*\d)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"VAT[\s.-]*ID[\s:]*([A-Z]{2}\s*\d[\d\s]*\d)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"Tax[\s.-]*ID[\s:]*([A-Z]{2}\s*\d[\d\s]*\d)", text, re.IGNORECASE)
    if m:
        result["vat_id"] = re.sub(r"\s", "", m.group(1))
        fields_found += 1

    # --- Amounts ---
    for key, patterns in _AMOUNT_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = _parse_german_number(m.group(1))
                if val is not None and val > 0:
                    result[f"{key}_amount"] = round(val, 2)
                    fields_found += 1
                    break

    # --- Try to infer missing amounts ---
    net = result.get("net_amount")
    tax = result.get("tax_amount")
    gross = result.get("gross_amount")
    if net and tax and not gross:
        result["gross_amount"] = round(net + tax, 2)
    elif gross and tax and not net:
        result["net_amount"] = round(gross - tax, 2)
    elif gross and net and not tax:
        result["tax_amount"] = round(gross - net, 2)

    # --- Partner name (heuristic: first non-empty line from the top) ---
    if "partner" not in result:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines[:10]:
            # Skip lines that look like dates, amounts, IDs, or short labels
            if re.match(r"^\d", line):
                continue
            if re.match(r"^(Rechnung|Invoice|Datum|Date|Seite|Page|Steuer|USt|Tel|Fax|E-?Mail|IBAN|BIC|www\.|http)", line, re.IGNORECASE):
                continue
            if len(line) < 3 or len(line) > 100:
                continue
            result["partner"] = line
            fields_found += 1
            break

    if fields_found < 2:
        return None, 0.0

    # --- Confidence score ---
    confidence = 0.0
    core_fields = ["id", "date", "partner", "net_amount", "tax_amount", "gross_amount"]
    present = sum(1 for f in core_fields if f in result)
    confidence = present / len(core_fields)

    # Bonus for amount consistency
    net = result.get("net_amount", 0)
    tax = result.get("tax_amount", 0)
    gross = result.get("gross_amount", 0)
    if net > 0 and tax >= 0 and gross > 0:
        expected = net + tax
        if abs(expected - gross) < gross * 0.02:
            confidence = min(confidence + 0.1, 1.0)
        else:
            confidence = max(confidence - 0.15, 0.0)

    return result, round(confidence, 2)


# ---------------------------------------------------------------------------
# Tier 3: LLM-based extraction via Claude API
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """You are a German invoice data extraction assistant.
Extract structured data from the provided invoice text.
Respond ONLY with a valid JSON object, no other text.

Required JSON fields:
- "id": invoice number (string)
- "date": invoice date as YYYY-MM-DD (string)
- "partner": vendor/supplier company name (string)
- "net_amount": net amount in EUR (number)
- "tax_amount": VAT/MwSt amount in EUR (number)
- "gross_amount": gross total in EUR (number)
- "vat_id": supplier USt-IdNr / VAT ID (string, empty string if not found)

Rules:
- Convert German date format (DD.MM.YYYY) to YYYY-MM-DD
- Convert German number format (1.234,56) to numeric (1234.56)
- If a field cannot be determined, use null
- net_amount + tax_amount should equal gross_amount"""


def parse_invoice_text_llm(text: str) -> tuple[dict | None, float]:
    """
    Extract invoice data using Claude API.
    Returns (data_dict | None, confidence 0.0-1.0).
    Gracefully returns (None, 0.0) if API key is not set or call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, 0.0

    try:
        import anthropic
    except ImportError:
        return None, 0.0

    model = os.environ.get("INVOICE_LLM_MODEL", "claude-sonnet-4-20250514")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_LLM_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Extract invoice data from this text:\n\n{text[:4000]}"}
            ],
        )

        raw = response.content[0].text.strip()

        # Try to parse JSON (handle potential markdown wrapping)
        json_str = raw
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            json_str = json_match.group(0)

        data = json.loads(json_str)

        # Validate and normalize
        result = {}
        for field in ["id", "date", "partner", "vat_id"]:
            val = data.get(field)
            if val is not None:
                result[field] = str(val)

        for field in ["net_amount", "tax_amount", "gross_amount"]:
            val = data.get(field)
            if val is not None:
                try:
                    result[field] = round(float(val), 2)
                except (ValueError, TypeError):
                    pass

        if len(result) < 2:
            return None, 0.0

        # Confidence based on completeness and consistency
        confidence = 0.85
        net = result.get("net_amount", 0)
        tax = result.get("tax_amount", 0)
        gross = result.get("gross_amount", 0)
        if net > 0 and gross > 0:
            expected = net + tax
            if abs(expected - gross) > gross * 0.02:
                confidence = 0.6

        core_fields = ["id", "date", "partner", "net_amount", "tax_amount", "gross_amount"]
        missing = sum(1 for f in core_fields if f not in result)
        confidence -= missing * 0.1

        return result, round(max(confidence, 0.1), 2)

    except Exception as e:
        print(f"LLM extraction error: {e}")
        return None, 0.0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def extract_invoice_from_text(pdf_bytes: bytes) -> tuple[dict | None, str, float]:
    """
    Attempt to extract invoice data from a plain PDF via text extraction.
    Returns (data_dict | None, method, confidence).
    method is one of: "regex", "llm", "no_text", "failed".
    """
    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        return None, "no_text", 0.0

    # Try regex first
    regex_data, regex_conf = parse_invoice_text_regex(text)

    if regex_data and regex_conf >= 0.7:
        return regex_data, "regex", regex_conf

    # Try LLM fallback
    llm_data, llm_conf = parse_invoice_text_llm(text)

    if llm_data and llm_conf > (regex_conf or 0):
        return llm_data, "llm", llm_conf

    # Return regex result even if low confidence
    if regex_data and regex_conf > 0:
        return regex_data, "regex", regex_conf

    return None, "failed", 0.0
