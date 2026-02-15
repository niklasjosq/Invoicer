import datetime
import xml.etree.ElementTree as ET

# Register namespaces to ensure correct prefixes in output
NAMESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}

for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)

def format_de(value):
    """
    Formats a float to German style: 1.250,00
    """
    if value is None:
        return "0,00"
    try:
        s = f"{float(value):,.2f}"
        return s.replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
    except (ValueError, TypeError):
        return "0,00"

def get_tax_scheme(tax_id):
    """
    Determines if the tax ID is a VAT ID (VA) or a local fiscal number (FC).
    Sanitizes the input by removing spaces.
    """
    if not tax_id:
        return None, None
    clean_id = tax_id.replace(" ", "").strip()
    # Simple heuristic: VAT IDs usually start with 2 letters (country code)
    if len(clean_id) > 2 and clean_id[:2].isalpha():
        return clean_id, "VA"
    else:
        return clean_id, "FC"

def parse_address_fields(lines):
    """
    Attempts to extract CityName and PostcodeCode from address lines.
    Assumes last line is 'Zip City' or 'City Zip' or similar.
    """
    postcode = ""
    city = ""
    line_one = lines[0] if len(lines) > 0 else ""
    
    if len(lines) > 1:
        # Try to parse the last line
        last_line = lines[-1].strip()
        parts = last_line.split(" ", 1)
        if len(parts) == 2:
            # Check if one part is numeric (Zip)
            if parts[0].isdigit():
                postcode = parts[0]
                city = parts[1]
            elif parts[1].isdigit():
                city = parts[0]
                postcode = parts[1]
            else:
                # Fallback: assume first part is city if no digit
                city = parts[0]
                postcode = parts[1]
        else:
            city = last_line
            
    return line_one, postcode, city

def generate_facturx_xml(data):
    """
    Generates strict Factur-X Basic Profile XML using ElementTree.
    Includes mandatory fields for XRechnung validation.
    """
    # 1. Root Element
    root = ET.Element(f"{{{NAMESPACES['rsm']}}}CrossIndustryInvoice")
    
    # 2. ExchangedDocumentContext
    context = ET.SubElement(root, f"{{{NAMESPACES['rsm']}}}ExchangedDocumentContext")
    guideline = ET.SubElement(context, f"{{{NAMESPACES['ram']}}}GuidelineSpecifiedDocumentContextParameter")
    guideline_id = ET.SubElement(guideline, f"{{{NAMESPACES['ram']}}}ID")
    guideline_id.text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"
    
    # 3. ExchangedDocument
    ex_doc = ET.SubElement(root, f"{{{NAMESPACES['rsm']}}}ExchangedDocument")
    doc_id = ET.SubElement(ex_doc, f"{{{NAMESPACES['ram']}}}ID")
    doc_id.text = data.get("id", "INV-001")
    
    doc_type = ET.SubElement(ex_doc, f"{{{NAMESPACES['ram']}}}TypeCode")
    doc_type.text = "380" # Commercial Invoice
    
    issue_date = ET.SubElement(ex_doc, f"{{{NAMESPACES['ram']}}}IssueDateTime")
    dt_str = ET.SubElement(issue_date, f"{{{NAMESPACES['udt']}}}DateTimeString", {"format": "102"})
    dt_str.text = data.get("date", datetime.date.today()).strftime("%Y%m%d")
    
    # 4. SupplyChainTradeTransaction
    transaction = ET.SubElement(root, f"{{{NAMESPACES['rsm']}}}SupplyChainTradeTransaction")
    
    # -- Line Items
    items = data.get("items", [])
    total_net = 0.0
    total_tax = 0.0
    
    for idx, item in enumerate(items, 1):
        line_item = ET.SubElement(transaction, f"{{{NAMESPACES['ram']}}}IncludedSupplyChainTradeLineItem")
        
        # AssociatedDocumentLineDocument
        line_doc = ET.SubElement(line_item, f"{{{NAMESPACES['ram']}}}AssociatedDocumentLineDocument")
        line_id = ET.SubElement(line_doc, f"{{{NAMESPACES['ram']}}}LineID")
        line_id.text = str(idx)
        
        # SpecifiedTradeProduct
        product = ET.SubElement(line_item, f"{{{NAMESPACES['ram']}}}SpecifiedTradeProduct")
        
        # BT-29: Global ID (optional) - Only generate if scheme is provided
        if item.get("global_id") and item.get("global_id_scheme"):
            g_id = ET.SubElement(product, f"{{{NAMESPACES['ram']}}}GlobalID", {"schemeID": item["global_id_scheme"]})
            g_id.text = item["global_id"]
            
        name = ET.SubElement(product, f"{{{NAMESPACES['ram']}}}Name")
        name.text = item.get("name", item.get("Description", "Item"))
        
        # SpecifiedLineTradeAgreement
        agreement = ET.SubElement(line_item, f"{{{NAMESPACES['ram']}}}SpecifiedLineTradeAgreement")
        price_node = ET.SubElement(agreement, f"{{{NAMESPACES['ram']}}}NetPriceProductTradePrice")
        charge = ET.SubElement(price_node, f"{{{NAMESPACES['ram']}}}ChargeAmount")
        unit_price = float(item.get("price", item.get("Price per Hour (€)", 0)))
        charge.text = f"{unit_price:.2f}"
        
        # SpecifiedLineTradeDelivery
        delivery_line = ET.SubElement(line_item, f"{{{NAMESPACES['ram']}}}SpecifiedLineTradeDelivery")
        qty = ET.SubElement(delivery_line, f"{{{NAMESPACES['ram']}}}BilledQuantity", {"unitCode": data.get("unit_code", "HUR")})
        qty_val = float(item.get("qty", item.get("Quantity (hours)", 0)))
        qty.text = f"{qty_val:.2f}"
        
        # SpecifiedLineTradeSettlement
        settlement_line = ET.SubElement(line_item, f"{{{NAMESPACES['ram']}}}SpecifiedLineTradeSettlement")
        
        tax_percent = float(item.get("vat_percent", 19.0))
        tax_line = ET.SubElement(settlement_line, f"{{{NAMESPACES['ram']}}}ApplicableTradeTax")
        
        # Line level tax for Basic profile should ONLY have: TypeCode, CategoryCode, RateApplicablePercent
        t_line_type = ET.SubElement(tax_line, f"{{{NAMESPACES['ram']}}}TypeCode")
        t_line_type.text = "VAT"
        t_line_cat = ET.SubElement(tax_line, f"{{{NAMESPACES['ram']}}}CategoryCode")
        t_line_cat.text = "S"
        t_line_rate = ET.SubElement(tax_line, f"{{{NAMESPACES['ram']}}}RateApplicablePercent")
        t_line_rate.text = f"{tax_percent:.2f}"
        
        line_summation = ET.SubElement(settlement_line, f"{{{NAMESPACES['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
        net_line = round(unit_price * qty_val, 2)
        l_total_amt = ET.SubElement(line_summation, f"{{{NAMESPACES['ram']}}}LineTotalAmount", {"currencyID": "EUR"})
        l_total_amt.text = f"{net_line:.2f}"
        
        total_net += net_line
        total_tax += round(net_line * (tax_percent / 100.0), 2)
        
    # -- Header Trade Agreement
    header_agreement = ET.SubElement(transaction, f"{{{NAMESPACES['ram']}}}ApplicableHeaderTradeAgreement")
    
    # Seller
    seller = ET.SubElement(header_agreement, f"{{{NAMESPACES['ram']}}}SellerTradeParty")
    s_name = ET.SubElement(seller, f"{{{NAMESPACES['ram']}}}Name")
    s_name.text = data.get("sender", {}).get("name", "Seller Name")
    
    s_address_node = ET.SubElement(seller, f"{{{NAMESPACES['ram']}}}PostalTradeAddress")
    s_l1, s_zip, s_city = parse_address_fields(data.get("sender", {}).get("address_lines", []))
    
    if s_zip:
        s_pc = ET.SubElement(s_address_node, f"{{{NAMESPACES['ram']}}}PostcodeCode")
        s_pc.text = s_zip
    if s_l1:
        s_line1 = ET.SubElement(s_address_node, f"{{{NAMESPACES['ram']}}}LineOne")
        s_line1.text = s_l1
    if s_city:
        s_city_name = ET.SubElement(s_address_node, f"{{{NAMESPACES['ram']}}}CityName")
        s_city_name.text = s_city
        
    s_country = ET.SubElement(s_address_node, f"{{{NAMESPACES['ram']}}}CountryID")
    s_country.text = "DE" # Placeholder
    
    if data.get("sender_tax_id"):
        clean_id, scheme = get_tax_scheme(data.get("sender_tax_id"))
        tax_reg = ET.SubElement(seller, f"{{{NAMESPACES['ram']}}}SpecifiedTaxRegistration")
        # BT-18: Only keep schemeID for VAT (VA). Proprietary IDs (FC etc) SHOULD NOT have schemeID attribute.
        if scheme == "VA":
            tr_id = ET.SubElement(tax_reg, f"{{{NAMESPACES['ram']}}}ID", {"schemeID": "VA"})
        else:
            tr_id = ET.SubElement(tax_reg, f"{{{NAMESPACES['ram']}}}ID")
        tr_id.text = clean_id
        
    # BT-18: AdditionalReferencedDocument (Object Identifier / Project Reference)
    if data.get("project_id"):
        ref_doc = ET.SubElement(header_agreement, f"{{{NAMESPACES['ram']}}}AdditionalReferencedDocument")
        # BT-18: IssuerAssignedID MUST NOT have schemeID attribute for proprietary references
        issuer_id = ET.SubElement(ref_doc, f"{{{NAMESPACES['ram']}}}IssuerAssignedID")
        issuer_id.text = str(data.get("project_id"))
        t_code = ET.SubElement(ref_doc, f"{{{NAMESPACES['ram']}}}TypeCode")
        t_code.text = "130" # 130 = Invoicing Data Sheet
        
    # BT-13: BuyerOrderReferencedDocument (Purchase Order Reference)
    if data.get("order_id"):
        order_ref = ET.SubElement(header_agreement, f"{{{NAMESPACES['ram']}}}BuyerOrderReferencedDocument")
        # BT-13: IssuerAssignedID MUST NOT have schemeID for proprietary IDs
        order_issuer_id = ET.SubElement(order_ref, f"{{{NAMESPACES['ram']}}}IssuerAssignedID")
        order_issuer_id.text = str(data.get("order_id"))
        
    buyer = ET.SubElement(header_agreement, f"{{{NAMESPACES['ram']}}}BuyerTradeParty")
    if data.get("customer_id"):
        # Removing schemeID for BT-18 compliance unless valid ICD code provided
        b_cid = ET.SubElement(buyer, f"{{{NAMESPACES['ram']}}}ID")
        b_cid.text = data.get("customer_id")
    
    b_name = ET.SubElement(buyer, f"{{{NAMESPACES['ram']}}}Name")
    b_name.text = data.get("recipient", {}).get("name", "Buyer Name")
    
    b_address_node = ET.SubElement(buyer, f"{{{NAMESPACES['ram']}}}PostalTradeAddress")
    b_l1, b_zip, b_city = parse_address_fields(data.get("recipient", {}).get("address_lines", []))
    
    if b_zip:
        b_pc = ET.SubElement(b_address_node, f"{{{NAMESPACES['ram']}}}PostcodeCode")
        b_pc.text = b_zip
    if b_l1:
        b_line1 = ET.SubElement(b_address_node, f"{{{NAMESPACES['ram']}}}LineOne")
        b_line1.text = b_l1
    if b_city:
        b_city_name = ET.SubElement(b_address_node, f"{{{NAMESPACES['ram']}}}CityName")
        b_city_name.text = b_city
        
    b_country = ET.SubElement(b_address_node, f"{{{NAMESPACES['ram']}}}CountryID")
    b_country.text = "DE" # Placeholder
    
    # -- Header Trade Delivery
    delivery_header = ET.SubElement(transaction, f"{{{NAMESPACES['ram']}}}ApplicableHeaderTradeDelivery")
    
    # -- Header Trade Settlement
    settlement_header = ET.SubElement(transaction, f"{{{NAMESPACES['ram']}}}ApplicableHeaderTradeSettlement")
    curr_settle = ET.SubElement(settlement_header, f"{{{NAMESPACES['ram']}}}InvoiceCurrencyCode")
    curr_settle.text = "EUR"
    
    # Payment Means
    payment = ET.SubElement(settlement_header, f"{{{NAMESPACES['ram']}}}SpecifiedTradeSettlementPaymentMeans")
    p_means_type = ET.SubElement(payment, f"{{{NAMESPACES['ram']}}}TypeCode")
    p_means_type.text = "58" # SEPA
    
    p_account = ET.SubElement(payment, f"{{{NAMESPACES['ram']}}}PayeePartyCreditorFinancialAccount")
    iban_elem = ET.SubElement(p_account, f"{{{NAMESPACES['ram']}}}IBANID")
    iban_elem.text = data.get("footer", {}).get("iban", "").replace(" ", "")
    
    # Tax Breakdown (Header)
    # Strictly enforced sequence: CalculatedAmount, TypeCode, BasisAmount, CategoryCode, RateApplicablePercent
    h_tax = ET.SubElement(settlement_header, f"{{{NAMESPACES['ram']}}}ApplicableTradeTax")
    
    h_tax_calc = ET.SubElement(h_tax, f"{{{NAMESPACES['ram']}}}CalculatedAmount", {"currencyID": "EUR"})
    h_tax_calc.text = f"{total_tax:.2f}"
    
    h_tax_type = ET.SubElement(h_tax, f"{{{NAMESPACES['ram']}}}TypeCode")
    h_tax_type.text = "VAT"
    
    h_tax_basis = ET.SubElement(h_tax, f"{{{NAMESPACES['ram']}}}BasisAmount", {"currencyID": "EUR"})
    h_tax_basis.text = f"{total_net:.2f}"
    
    h_tax_cat = ET.SubElement(h_tax, f"{{{NAMESPACES['ram']}}}CategoryCode")
    h_tax_cat.text = "S"
    
    h_tax_rate = ET.SubElement(h_tax, f"{{{NAMESPACES['ram']}}}RateApplicablePercent")
    h_tax_rate.text = "19.00"
    
    # BT-9 / BT-20: SpecifiedTradePaymentTerms
    terms = ET.SubElement(settlement_header, f"{{{NAMESPACES['ram']}}}SpecifiedTradePaymentTerms")
    issue_dt = data.get("date", datetime.date.today())
    due_dt = data.get("due_date")
    if not due_dt:
        due_dt = issue_dt + datetime.timedelta(days=14)
    
    due_dt_node = ET.SubElement(terms, f"{{{NAMESPACES['ram']}}}DueDateDateTime")
    due_dt_str = ET.SubElement(due_dt_node, f"{{{NAMESPACES['udt']}}}DateTimeString", {"format": "102"})
    due_dt_str.text = due_dt.strftime("%Y%m%d")
    
    total_net = round(total_net, 2)
    total_tax = round(total_tax, 2)
    grand_total = round(total_net + total_tax, 2)

    # Monetary Summation
    summation = ET.SubElement(settlement_header, f"{{{NAMESPACES['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
    s_line_total = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}LineTotalAmount", {"currencyID": "EUR"})
    s_line_total.text = f"{total_net:.2f}"
    s_charge = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}ChargeTotalAmount", {"currencyID": "EUR"})
    s_charge.text = "0.00"
    s_allowance = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}AllowanceTotalAmount", {"currencyID": "EUR"})
    s_allowance.text = "0.00"
    s_tax_basis = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}TaxBasisTotalAmount", {"currencyID": "EUR"})
    s_tax_basis.text = f"{total_net:.2f}"
    s_tax_total = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}TaxTotalAmount", {"currencyID": "EUR"})
    s_tax_total.text = f"{total_tax:.2f}"
    s_grand = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}GrandTotalAmount", {"currencyID": "EUR"})
    s_grand.text = f"{grand_total:.2f}"
    s_due = ET.SubElement(summation, f"{{{NAMESPACES['ram']}}}DuePayableAmount", {"currencyID": "EUR"})
    s_due.text = f"{grand_total:.2f}"
    
    # Serialize
    xml_bytes = ET.tostring(root, encoding="utf-8")
    xml_str = xml_bytes.decode("utf-8")
    if not xml_str.startswith("<?xml"):
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
        
    return xml_str

from fpdf import FPDF
from fpdf.output import PDFICCProfile
from fpdf.enums import OutputIntentSubType
from drafthorse.pdf import attach_xml
import os

def generate_invoice_pdf(data):
    """
    Generates visual PDF using fpdf2.
    """
    pdf = FPDF()
    
    # Add Fonts (Arial)
    # Ensure assets exist
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    arial_path = os.path.join(assets_dir, "Arial.ttf")
    arial_bold_path = os.path.join(assets_dir, "Arial_Bold.ttf")
    
    if os.path.exists(arial_path):
        pdf.add_font("Arial", style="", fname=arial_path)
    if os.path.exists(arial_bold_path):
        pdf.add_font("Arial", style="B", fname=arial_bold_path)
        
    pdf.add_page()
    
    # Add ICC Profile for PDF/A-3 Compliance (resolves DeviceGray error)
    icc_path = os.path.join(assets_dir, "sRGB.icc")
    if os.path.exists(icc_path):
        with open(icc_path, "rb") as f:
            icc_bytes = f.read()
        # n=3 for RGB
        profile = PDFICCProfile(icc_bytes, 3, "DeviceRGB")
        pdf.add_output_intent(
            subtype=OutputIntentSubType.PDFA, 
            output_condition_identifier="sRGB IEC61966-2.1", 
            dest_output_profile=profile,
            info="sRGB IEC61966-2.1"
        )
        
    # Use Arial if available, else fallback to Helvetica (though internal Helvetica is not embedded)
    font_family = "Arial" if os.path.exists(arial_path) else "Helvetica"
    
    pdf.set_font(font_family, size=12)
    
    # Title
    pdf.set_font(font_family, style="B", size=20)
    pdf.cell(0, 10, "RECHNUNG", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)
    
    # Details
    pdf.set_font(font_family, size=12)
    pdf.cell(0, 6, f"Rechnungsnummer: {data.get('id', 'INV-001')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Datum: {data.get('date', datetime.date.today()).strftime('%d.%m.%Y')}", new_x="LMARGIN", new_y="NEXT")
    
    if data.get("customer_id"):
        pdf.cell(0, 6, f"Kundennummer: {data.get('customer_id')}", new_x="LMARGIN", new_y="NEXT")

    if data.get("delivery_date"):
        dd = data.get("delivery_date")
        if isinstance(dd, (list, tuple)) and len(dd) == 2:
            start_str = dd[0].strftime('%d.%m.%Y')
            end_str = dd[1].strftime('%d.%m.%Y')
            pdf.cell(0, 6, f"Leistungszeitraum: {start_str} - {end_str}", new_x="LMARGIN", new_y="NEXT")
        elif isinstance(dd, (list, tuple)) and len(dd) == 1:
            pdf.cell(0, 6, f"Leistungsdatum: {dd[0].strftime('%d.%m.%Y')}", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.cell(0, 6, f"Leistungsdatum: {dd.strftime('%d.%m.%Y')}", new_x="LMARGIN", new_y="NEXT")
        
    pdf.ln(5)
    
    # Sender and Recipient
    col_width = pdf.epw / 2
    
    pdf.set_font(font_family, style="B", size=11)
    pdf.cell(col_width, 6, "Absender:", border=0)
    pdf.cell(col_width, 6, "Empfänger:", border=0, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_family, size=11)
    
    # Construct full address strings
    sender_lines = [data["sender"].get("name", "")] + data["sender"].get("address_lines", [])
    sender_str = "\n".join(sender_lines)
    
    recipient_lines = [data["recipient"].get("name", "")] + data["recipient"].get("address_lines", [])
    recipient_str = "\n".join(recipient_lines)
    
    # Save Y position
    start_y = pdf.get_y()
    
    # Sender (Left)
    pdf.multi_cell(col_width, 6, sender_str, border=0)
    
    # Recipient (Right) - move to right column
    end_y_left = pdf.get_y()
    pdf.set_xy(pdf.l_margin + col_width, start_y)
    pdf.multi_cell(col_width, 6, recipient_str, border=0)
    
    # Move to max Y
    final_y = max(end_y_left, pdf.get_y())
    pdf.set_y(final_y + 10)
    
    # Subject
    if data.get("subject"):
        pdf.set_font(font_family, style="B", size=12)
        pdf.cell(0, 8, data.get("subject"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    
    # Table Header
    pdf.set_font(font_family, style="B", size=10)
    pdf.cell(70, 8, "Beschreibung", border=1)
    pdf.cell(30, 8, "Menge", border=1, align="R")
    pdf.cell(35, 8, "Preis/Einheit", border=1, align="R")
    pdf.cell(30, 8, "Netto", border=1, align="R")
    pdf.cell(25, 8, "Gesamt", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    # Table Rows
    pdf.set_font(font_family, size=10)
    total_net = 0.0
    total_tax_accumulated = 0.0
    
    for item in data.get("items", []):
        desc = item.get("name", item.get("Description", ""))
        qty = float(item.get("qty", item.get("Quantity (hours)", 0)) or 0)
        price = float(item.get("price", item.get("Price per Hour (€)", 0)) or 0)
        vat_rate = float(item.get("vat_percent", 19.0)) / 100.0
        
        net_line = round(qty * price, 2)
        tax_line = round(net_line * vat_rate, 2)
        total_incl = net_line + tax_line
        
        total_net += net_line
        total_tax_accumulated += tax_line
        
        pdf.cell(70, 8, desc, border=1)
        pdf.cell(30, 8, format_de(qty), border=1, align="R")
        pdf.cell(35, 8, format_de(price), border=1, align="R")
        pdf.cell(30, 8, format_de(net_line), border=1, align="R")
        pdf.cell(25, 8, format_de(total_incl), border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        
    # Total
    total_gross = total_net + total_tax_accumulated
    
    pdf.ln(5)
    pdf.set_font(font_family, style="B", size=10)
    pdf.cell(135, 8, "Summe Netto:", align="R")
    pdf.cell(55, 8, f"{format_de(total_net)} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    pdf.cell(135, 8, "MwSt 19%:", align="R")
    pdf.cell(55, 8, f"{format_de(total_tax_accumulated)} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    pdf.cell(135, 8, "Gesamtbetrag:", align="R")
    pdf.cell(55, 8, f"{format_de(total_gross)} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    # Payment Terms logic
    pdf.ln(10)
    pdf.set_font(font_family, size=10)
    if data.get("due_date"):
        pdf.cell(0, 5, f"Zahlbar ohne Abzug bis zum {data.get('due_date').strftime('%d.%m.%Y')}.", new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.set_y(-40)
    pdf.set_font(font_family, size=8)
    footer = data.get("footer", {})
    
    # Footer Columns
    # We use manual positioning for footer columns to be clean
    base_y = pdf.get_y()
    
    # Col 1
    pdf.set_xy(pdf.l_margin, base_y)
    pdf.multi_cell(50, 4, footer.get("col1", ""))
    
    # Col 2
    pdf.set_xy(pdf.l_margin + 60, base_y)
    pdf.multi_cell(60, 4, footer.get("col2", ""))
    
    # Col 3
    pdf.set_xy(pdf.l_margin + 130, base_y)
    pdf.multi_cell(50, 4, footer.get("col3", ""))

    return bytes(pdf.output())

def create_zugferd_pdf(pdf_bytes, xml_content):
    """
    Combines PDF and XML into ZUGFeRD PDF/A-3.
    """
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")
    
    output_pdf = attach_xml(pdf_bytes, xml_content, level="EN 16931")
    return output_pdf
