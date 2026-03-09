import datetime
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pypdf import PdfReader

# Namespaces for parsing Factur-X / ZUGFeRD
NAMESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}

# KATEGORIE_MAPPING: Maps user-friendly categories to ELSTER Kennzahlen (Kz)
# Distinguish between Ausgangsrechnungen (Einnahme) and Eingangsrechnungen (Ausgabe)
# kz_base: Field for the base amount (Bemessungsgrundlage) - usually rounded down to full EUR
# tax_rate: Tax rate for calculating output tax (if applicable)
# kz_tax: Field for the input tax amount (Vorsteuer) or deductible tax
# type: Transaction type (Einnahme = Ausgangsrechnung, Ausgabe = Eingangsrechnung)
KATEGORIE_MAPPING = {
    # ============ AUSGANGSRECHNUNGEN (Einnahme) ============
    "Aus: Umsatzerlöse (Waren/Erzeugnisse) 19%": {
        "kz_base": "81", 
        "tax_rate": 0.19, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    "Aus: Umsatzerlöse (Waren/Erzeugnisse) 7%": {
        "kz_base": "86", 
        "tax_rate": 0.07, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    "Aus: Umsatzerlöse (Dienstleistungen) 19%": {
        "kz_base": "81", 
        "tax_rate": 0.19, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    "Aus: Umsatzerlöse (Dienstleistungen) 7%": {
        "kz_base": "86", 
        "tax_rate": 0.07, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    "Aus: Abschlagsrechnungen/Teilleistungen 19%": {
        "kz_base": "81", 
        "tax_rate": 0.19, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    "Aus: Abschlagsrechnungen/Teilleistungen 7%": {
        "kz_base": "86", 
        "tax_rate": 0.07, 
        "kz_tax": None, 
        "type": "Einnahme",
        "group": "Ausgangsrechnungen"
    },
    
    # ============ EINGANGSRECHNUNGEN (Ausgabe) ============
    "Ein: Vorsteuer (Waren) 19%": {
        "kz_base": None, 
        "tax_rate": 0.0, 
        "kz_tax": "66",
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    },
    "Ein: Vorsteuer (Waren) 7%": {
        "kz_base": None, 
        "tax_rate": 0.0, 
        "kz_tax": "66", 
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    },
    "Ein: Vorsteuer (Dienstleistungen) 19%": {
        "kz_base": None, 
        "tax_rate": 0.0, 
        "kz_tax": "66",
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    },
    "Ein: Vorsteuer (Dienstleistungen) 7%": {
        "kz_base": None, 
        "tax_rate": 0.0, 
        "kz_tax": "66", 
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    },
    "Ein: Innergemeinschaftlicher Erwerb 19%": {
        "kz_base": "89",
        "tax_rate": 0.19,
        "kz_tax": "61",
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    },
    "Ein: Übrige Betriebsausgaben": {
        "kz_base": None,
        "tax_rate": 0.0,
        "kz_tax": "66",
        "type": "Ausgabe",
        "group": "Eingangsrechnungen"
    }
}

def parse_facturx_xml(xml_content):
    """
    Parses Factur-X/ZUGFeRD XML content (bytes or string) and returns a transaction dictionary.
    """
    try:
        if isinstance(xml_content, bytes):
             tree = ET.ElementTree(ET.fromstring(xml_content))
        else:
             tree = ET.ElementTree(ET.fromstring(xml_content))
             
        root_xml = tree.getroot()
        
        def find_text(xpath):
            elem = root_xml.find(xpath, NAMESPACES)
            return elem.text if elem is not None else ""

        # Extract Fields
        # Invoice Number
        inv_id = find_text(".//rsm:ExchangedDocument/ram:ID")
        
        # Date
        date_str = find_text(".//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
        # Format usually YYYYMMDD
        inv_date = None
        if date_str and len(date_str) == 8:
            inv_date = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        # Partner (Seller)
        partner_name = find_text(".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name")
        
        # Partner VAT ID
        # Looking for SchemeID=VA for VAT
        seller_vat_id = ""
        # Often just the first ID under SpecifiedTaxRegistration is VAT ID, but let's check scheme
        tax_regs = root_xml.findall(".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:SpecifiedTaxRegistration", NAMESPACES)
        for tr in tax_regs:
            tid = tr.find("ram:ID", NAMESPACES)
            if tid is not None and tid.get("schemeID") == "VA":
                seller_vat_id = tid.text
                break
        if not seller_vat_id and tax_regs:
            # Fallback: take first one if no scheme match
            first_tid = tax_regs[0].find("ram:ID", NAMESPACES)
            if first_tid is not None:
                seller_vat_id = first_tid.text

        # Heuristic for Category (incoming invoices are Ausgabe/Eingangsrechnungen)
        category = "Ein: Übrige Betriebsausgaben"
        # If Seller is non-German EU -> Innergemeinschaftlicher Erwerb
        # Common EU prefixes: AT, BE, BG, CY, CZ, DK, EE, ES, FI, FR, GR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK
        eu_prefixes = ["AT", "BE", "BG", "CY", "CZ", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
        
        if seller_vat_id:
            prefix = seller_vat_id[:2].upper()
            if prefix != "DE" and prefix in eu_prefixes:
                category = "Ein: Innergemeinschaftlicher Erwerb 19%"
            elif prefix == "DE":
                category = "Ein: Vorsteuer (Dienstleistungen) 19%"  # Default for domestic, assume services

        # Amounts
        # GrandTotalAmount is Gross
        gross_str = find_text(".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount")
        # TaxBasisTotalAmount is Net
        net_str = find_text(".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount")
        # TaxTotalAmount is Tax
        tax_str = find_text(".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount")
        
        return {
            "id": inv_id,
            "date": inv_date,
            "partner": partner_name,
            "net_amount": float(net_str) if net_str else 0.0,
            "tax_amount": float(tax_str) if tax_str else 0.0,
            "gross_amount": float(gross_str) if gross_str else 0.0,
            "type": "Ausgabe", # Incoming invoice is an expense
            "payment_date": None,
            "category": category,
            "vat_id": seller_vat_id
        }
    except Exception as e:
        print(f"Error parsing XML: {e}")
        return None

def extract_data_from_xml_file(xml_path):
    """
    Reads an XML file and extracts invoice data.
    """
    try:
        with open(xml_path, "rb") as f:
            content = f.read()
        return parse_facturx_xml(content)
    except Exception as e:
        print(f"Error reading XML file {xml_path}: {e}")
        return None

def extract_data_from_pdf(pdf_input):
    """
    Extracts invoice data from an embedded Factur-X/ZUGFeRD XML in a PDF.
    Accepts bytes or file path (str).
    """
    try:
        if isinstance(pdf_input, str):
            with open(pdf_input, "rb") as f:
                pdf_bytes = f.read()
        else:
            pdf_bytes = pdf_input
            
        reader = PdfReader(BytesIO(pdf_bytes))
        root = reader.trailer["/Root"]
        
        xml_content = None
        
        # pypdf > 3.0 approach for attachments
        if reader.attachments:
            for filename, data in reader.attachments.items():
                if filename.lower() in ["factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"]:
                    xml_content = data[0] # pypdf returns [bytes, dict]
                    break
        
        # Fallback
        if not xml_content:
            try:
                names = root["/Names"]
                embedded = names["/EmbeddedFiles"]
                name_array = embedded["/Names"]
                for i in range(0, len(name_array), 2):
                    fname = name_array[i]
                    if fname.lower() in ["factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"]:
                        file_spec = name_array[i+1].get_object()
                        xml_content = file_spec["/EF"]["/F"].get_object().get_data()
                        break
            except:
                pass

        if not xml_content:
            return None

        return parse_facturx_xml(xml_content)
        
    except Exception as e:
        print(f"Error extracting PDF data: {e}")
        return None

def _to_decimal(value):
    """
    Safely convert arbitrary numeric input to Decimal.
    Handles values coming from Streamlit editors (float/str/None).
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        raw = str(value).strip()
        if not raw:
            return Decimal("0")
        # Accept comma decimals from imported/stringified data.
        return Decimal(raw.replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

def _to_money(value):
    """
    Normalize to currency precision (2 decimals, commercial rounding).
    """
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _full_euro_base(value):
    """
    Convert a net base amount to full EUR for Kz81/86/89.
    """
    return int(_to_money(value))

def calculate_ustva_totals(transactions, month, year):
    """
    Calculates UStVA-relevant sums for a given period.
    Returns values used both by UI metrics and ELSTER XML generation.
    """
    kz_base_sums = {}
    kz_input_tax_sums = {}
    count_relevant = 0

    for t in transactions:
        pd = t.get("payment_date")
        if not pd:
            continue

        if isinstance(pd, str):
            try:
                pd = datetime.datetime.strptime(pd, "%Y-%m-%d").date()
            except ValueError:
                continue

        if not isinstance(pd, (datetime.date, datetime.datetime)):
            continue

        if pd.year != year or pd.month != month:
            continue

        count_relevant += 1

        net = _to_money(t.get("net_amount", 0))
        tax = _to_money(t.get("tax_amount", 0))

        cat = t.get("category", "")
        mapping = KATEGORIE_MAPPING.get(cat)

        # Fallback mapping if not exact match
        if not mapping:
            if t.get("type") == "Ausgabe":
                mapping = KATEGORIE_MAPPING.get("Ein: Übrige Betriebsausgaben")
            elif t.get("type") == "Einnahme":
                mapping = KATEGORIE_MAPPING.get("Aus: Umsatzerlöse (Dienstleistungen) 19%")

        if not mapping:
            continue

        kz_base = mapping.get("kz_base")
        if kz_base:
            kz_base_sums[kz_base] = kz_base_sums.get(kz_base, Decimal("0.00")) + net

        kz_tax = mapping.get("kz_tax")
        if kz_tax:
            if kz_tax == "61":
                deductible = _to_money(net * _to_decimal(mapping.get("tax_rate", 0.19)))
            else:
                deductible = tax
            kz_input_tax_sums[kz_tax] = kz_input_tax_sums.get(kz_tax, Decimal("0.00")) + deductible

    kz_base_rounded = {kz: _full_euro_base(val) for kz, val in kz_base_sums.items()}

    sum_sales_vat = Decimal("0.00")
    sum_sales_vat += Decimal(kz_base_rounded.get("81", 0)) * Decimal("0.19")
    sum_sales_vat += Decimal(kz_base_rounded.get("86", 0)) * Decimal("0.07")
    sum_sales_vat += Decimal(kz_base_rounded.get("89", 0)) * Decimal("0.19")
    sum_sales_vat = _to_money(sum_sales_vat)

    sum_input_tax = _to_money(
        kz_input_tax_sums.get("66", Decimal("0.00")) + kz_input_tax_sums.get("61", Decimal("0.00"))
    )
    zahllast = _to_money(sum_sales_vat - sum_input_tax)

    return {
        "count_relevant": count_relevant,
        "kz_base_sums": {kz: float(val) for kz, val in kz_base_sums.items()},
        "kz_base_rounded": kz_base_rounded,
        "kz_input_tax_sums": {kz: float(_to_money(val)) for kz, val in kz_input_tax_sums.items()},
        "sum_sales_vat": float(sum_sales_vat),
        "sum_input_tax": float(sum_input_tax),
        "zahllast": float(zahllast),
    }

def generate_ustva_xml(transactions, month, year, stnr="", name="", vorname=""):
    """
    Generates a rudimentary ELSTER UStVA XML.
    Filters transactions by payment_date matching month/year.
    """
    totals = calculate_ustva_totals(transactions, month, year)
    kz_base_rounded = totals["kz_base_rounded"]
    kz_input_tax_sums = totals["kz_input_tax_sums"]
    base_81 = kz_base_rounded.get("81", 0)
    base_86 = kz_base_rounded.get("86", 0)
    base_89 = kz_base_rounded.get("89", 0)
    val_66 = kz_input_tax_sums.get("66", 0.0)
    val_61 = kz_input_tax_sums.get("61", 0.0)
    kz_83 = totals["zahllast"]
    
    # Formatting helper
    def fmt_amt(val):
        return f"{val:.2f}"
    
    # XML Structure for "Mein ELSTER" Import (Formular-Import)
    # Namespace matches the year version (e.g., v2025, v2026)
    ns_url = f"http://finkonsens.de/elster/elsteranmeldung/ustva/v{year}"
    
    root = ET.Element("Anmeldungssteuern", {
        "xmlns": ns_url,
        "version": str(year)
    })

    # Compatibility for ELSTER form import:
    # include creation date on root level.
    ET.SubElement(root, "Erstellungsdatum").text = datetime.date.today().strftime("%Y%m%d")
    
    steuerfall = ET.SubElement(root, "Steuerfall")

    unternehmer = ET.SubElement(steuerfall, "Unternehmer")
    ET.SubElement(unternehmer, "StNr").text = str(stnr or "")
    ET.SubElement(unternehmer, "Name").text = str(name or "")
    ET.SubElement(unternehmer, "Vorname").text = str(vorname or "")

    ustva = ET.SubElement(steuerfall, "Umsatzsteuervoranmeldung")
    
    ET.SubElement(ustva, "Jahr").text = str(year)
    ET.SubElement(ustva, "Zeitraum").text = f"{month:02d}"
    if stnr:
        ET.SubElement(ustva, "Steuernummer").text = str(stnr)
    
    # Populate Fields
    # Bemessungsgrundlagen: Full Euro (integer)
    if base_81 > 0:
        ET.SubElement(ustva, "Kz81").text = str(int(base_81))
    if base_86 > 0:
        ET.SubElement(ustva, "Kz86").text = str(int(base_86))
    if base_89 > 0:
        ET.SubElement(ustva, "Kz89").text = str(int(base_89))
        
    # Steuerbeträge: 2 decimals
    if val_66 > 0:
        ET.SubElement(ustva, "Kz66").text = fmt_amt(val_66)
    if val_61 > 0:
        ET.SubElement(ustva, "Kz61").text = fmt_amt(val_61)
        
    # Kz 83 is mandatory usually
    ET.SubElement(ustva, "Kz83").text = fmt_amt(kz_83)
    
    # Generate bytes with correct encoding
    # We use ISO-8859-15 as requested by ELSTER
    # xml_declaration=False prevents ET from adding its own header (avoiding duplication)
    xml_bytes = ET.tostring(root, encoding="iso-8859-15", xml_declaration=False)
    
    # Prepend the correct XML declaration manually
    header = b'<?xml version="1.0" encoding="ISO-8859-15" standalone="no"?>\n'
    
    return header + xml_bytes

def generate_euer_xml(transactions, year):
    """
    Generates a rudimentary ELSTER EÜR XML.
    Filters transactions by payment_date matching year.
    Groups by category.
    """
    relevant = []
    for t in transactions:
        pd = t.get("payment_date")
        if pd:
            if isinstance(pd, str):
                pd_obj = datetime.datetime.strptime(pd, "%Y-%m-%d").date()
            else:
                pd_obj = pd
                
            if pd_obj.year == year:
                relevant.append(t)
    
    total_income = sum(t["net_amount"] for t in relevant if t["type"] == "Einnahme")
    total_expenses = sum(t["net_amount"] for t in relevant if t["type"] == "Ausgabe")
    profit = total_income - total_expenses
    
    # XML
    root = ET.Element("Elster")
    transfer_header = ET.SubElement(root, "TransferHeader")
    ET.SubElement(transfer_header, "Verfahren").text = "ElsterErklaerung"
    ET.SubElement(transfer_header, "DatenArt").text = "EÜR"
    
    daten_teil = ET.SubElement(root, "DatenTeil")
    nutzdaten_block = ET.SubElement(daten_teil, "Nutzdatenblock")
    nutzdaten = ET.SubElement(nutzdaten_block, "Nutzdaten")
    euer = ET.SubElement(nutzdaten, f"Euer{year}")
    
    # Einnahmen
    einnahmen_node = ET.SubElement(euer, "Einnahmen")
    # Using a generic field for "Betriebseinnahmen" (e.g. Kz 11 or similar mapping)
    # Since this is rudimentary, we label it clearly.
    ET.SubElement(einnahmen_node, "SummeBetriebseinnahmen").text = f"{total_income:.2f}"
    
    # Ausgaben
    ausgaben_node = ET.SubElement(euer, "Ausgaben")
    ET.SubElement(ausgaben_node, "SummeBetriebsausgaben").text = f"{total_expenses:.2f}"
    
    # Breakdown by category (Optional for rudimentary, but helpful)
    for cat in set(t["category"] for t in relevant if t["type"] == "Ausgabe"):
        cat_sum = sum(t["net_amount"] for t in relevant if t["type"] == "Ausgabe" and t["category"] == cat)
        cat_node = ET.SubElement(ausgaben_node, "Posten")
        cat_node.set("Bezeichnung", cat)
        cat_node.text = f"{cat_sum:.2f}"

    # Gewinn
    gewinn_node = ET.SubElement(euer, "Gewinnermittlung")
    ET.SubElement(gewinn_node, "SteuerpflichtigerGewinn").text = f"{profit:.2f}"
    
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    return f'<?xml version="1.0" encoding="ISO-8859-15"?>\n{xml_str}'
