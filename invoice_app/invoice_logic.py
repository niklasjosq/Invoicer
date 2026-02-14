import datetime
from drafthorse.models.document import Document, Header
from drafthorse.models.trade import TradeTransaction
from drafthorse.models.tradelines import LineItem
from drafthorse.models.party import SellerTradeParty, BuyerTradeParty, TaxRegistration
from drafthorse.models.payment import PaymentTerms, PaymentMeans, PayeeFinancialAccount, PayeeFinancialInstitution
from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.note import IncludedNote

# Monkey Patch: Remove 'Name' from Header fields as it causes validation error in EN16931 profile
# Drafthorse defines it as required, but ZUGFeRD schema order/presence rules reject it.
if hasattr(Header, "_fields"):
    Header._fields = [f for f in Header._fields if f.name != "Name"]

def format_de(value):
    """
    Formats a float to German style: 1.250,00
    """
    if value is None:
        return "0,00"
    try:
        # Format with 2 decimals and comma as decimal, dot as thousands
        # Manual replacement to avoid locale issues
        s = f"{float(value):,.2f}"
        # Swap US format (,) to temp, US (.) to (,), temp to (.)
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
    # e.g. DE123456789
    if len(clean_id) > 2 and clean_id[:2].isalpha():
        return clean_id, "VA"
    else:
        return clean_id, "FC"

def generate_invoice_xml(data):
    """
    Generates ZUGFeRD XML from the provided data dictionary.
    """
    doc = Document()
    # Use standard ZUGFeRD 2.3 / EN16931 ID
    doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931"
    
    # Header
    doc.header.id = data.get("id", "INV-001")
    # doc.header.name = "RECHNUNG" # Not allowed in EN16931
    doc.header.type_code = "380" # Commercial Invoice
    doc.header.issue_date_time = data.get("date", datetime.date.today())
    
    # Trade Agreement
    doc.trade.agreement.seller.name = data["sender"].get("name", "Unknown Seller")
    # Map address lines to ZUGFeRD structure (simplified: just lines 1-3)
    seller_addr = data["sender"].get("address_lines", [])
    if len(seller_addr) > 0: doc.trade.agreement.seller.address.line_one = seller_addr[0]
    if len(seller_addr) > 1: doc.trade.agreement.seller.address.line_two = seller_addr[1]
    if len(seller_addr) > 2: doc.trade.agreement.seller.address.line_three = seller_addr[2]
    doc.trade.agreement.seller.address.country_id = "DE" # Defaulting to DE fow now
    
    if data.get("sender_tax_id"):
        tid, scheme = get_tax_scheme(data.get("sender_tax_id"))
        if tid:
            tr = TaxRegistration()
            tr.id = tid
            tr.id._scheme_id = scheme 
            doc.trade.agreement.seller.tax_registrations.add(tr)

    doc.trade.agreement.buyer.name = data["recipient"].get("name", "Unknown Buyer")
    doc.trade.agreement.buyer.id = data.get("customer_id") # Customer ID
    
    buyer_addr = data["recipient"].get("address_lines", [])
    if len(buyer_addr) > 0: doc.trade.agreement.buyer.address.line_one = buyer_addr[0]
    if len(buyer_addr) > 1: doc.trade.agreement.buyer.address.line_two = buyer_addr[1]
    if len(buyer_addr) > 2: doc.trade.agreement.buyer.address.line_three = buyer_addr[2]
    doc.trade.agreement.buyer.address.country_id = "DE" 
    
    # Delivery / Service Date
    if data.get("delivery_date"):
        dd = data.get("delivery_date")
        if isinstance(dd, (list, tuple)) and len(dd) >= 1:
            # Handle single date in range widget or full range
            doc.trade.delivery.event.occurrence = dd[0] # Using start date for occurrence
        else:
            doc.trade.delivery.event.occurrence = dd
        
    # Payment Terms / Due Date
    if data.get("due_date"):
        terms = PaymentTerms()
        terms.due = data.get("due_date")
        terms.description = f"Zahlbar bis zum {data.get('due_date').strftime('%d.%m.%Y')}"
        doc.trade.settlement.terms.add(terms)
    
    # Bank Details
    footer = data.get("footer", {})
    if footer.get("iban"):
        pm = PaymentMeans()
        pm.type_code = "58" # SEPA Credit Transfer
        
        pm.payee_account.iban = footer.get("iban")
        pm.payee_institution.bic = footer.get("bic")
        
        doc.trade.settlement.payment_means.add(pm)
    
    # Note / Subject
    if data.get("subject"):
        note = IncludedNote()
        note.content = data.get("subject")
        doc.header.notes.add(note)
    
    # Items and Totals
    total_net = 0.0
    total_tax = 0.0
    
    for item in data.get("items", []):
        li = LineItem()
        li.document.line_id = str(len(doc.trade.items.children) + 1)
        li.product.name = item.get("Description") or "Item"
        
        # New keys from UI
        # We respect the Total provided by the UI (which handles calculation/manual override)
        net_line = float(item.get("Total (€)", 0) or 0)
        # Fallback if Total is 0 but Qty/Price exist (though UI handles this)
        qty = float(item.get("Quantity (hours)", 0) or 0)
        price = float(item.get("Price per Hour (€)", 0) or 0)
        if net_line == 0 and (qty * price) != 0:
             net_line = qty * price
             
        tax_amount = float(item.get("Tax 19% (€)", 0) or 0)  
        
        # Let's use the UI's values for totals
        if tax_amount == 0 and net_line != 0:
            tax_amount = net_line * 0.19
            
        tax_percent = 19.0 # We still claiming it's 19% VAT standard
        
        li.delivery.billed_quantity = (qty, data.get("unit_code", "HUR")) 
        li.agreement.net.amount = price
        li.settlement.monetary_summation.total_amount = net_line
        
        # Add tax details to line (single field in drafthorse LineSettlement)
        li.settlement.trade_tax.type_code = "VAT"
        li.settlement.trade_tax.category_code = "S" # Standard rate
        li.settlement.trade_tax.rate_applicable_percent = tax_percent
        
        doc.trade.items.add(li)
        
        total_net += net_line
        total_tax += tax_amount

    # Totals
    doc.trade.settlement.monetary_summation.line_total = total_net
    doc.trade.settlement.monetary_summation.charge_total = 0.0
    doc.trade.settlement.monetary_summation.allowance_total = 0.0
    doc.trade.settlement.monetary_summation.tax_basis_total = total_net
    doc.trade.settlement.monetary_summation.tax_total = (total_tax, "EUR")
    doc.trade.settlement.monetary_summation.grand_total = (total_net + total_tax, "EUR")
    doc.trade.settlement.monetary_summation.due_amount = total_net + total_tax
    doc.trade.settlement.currency_code = "EUR"
    
    # Add a tax breakdown (container)
    tax = ApplicableTradeTax()
    tax.type_code = "VAT"
    tax.category_code = "S"
    tax.basis_amount = total_net
    tax.calculated_amount = total_tax
    tax.rate_applicable_percent = 19.0 # Placeholder
    doc.trade.settlement.trade_tax.add(tax)

    # Serialize to XML string
    xml_str = doc.serialize(schema="FACTUR-X_EN16931").decode("utf-8")
    
    # Post-process XML to inject schemeID for Buyer ID (drafthorse doesn't support it on StringField)
    try:
        import xml.etree.ElementTree as ET
        
        # Register namespaces to prevent ns0 prefixes
        namespaces = {
            "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
            "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
            "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
            "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
        }
        for prefix, uri in namespaces.items():
            ET.register_namespace(prefix, uri)
            
        root = ET.fromstring(xml_str)
        
        # Find Buyer ID
        # XPath: rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:ID
        buyer_id = root.find(".//ram:BuyerTradeParty/ram:ID", namespaces)
        
        if buyer_id is not None and buyer_id.text:
            # Set schemeID="91" (Seller assigned)
            buyer_id.set("schemeID", "91")
            
        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        
        # Add XML declaration if missing (ET.tostring might omit it or add it differently)
        if not xml_str.startswith("<?xml"):
            xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
            
    except Exception as e:
        print(f"Error post-processing XML: {e}")
        # Fallback to original if hack fails
        pass

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
        desc = item.get("Description", "")
        qty = float(item.get("Quantity (hours)", 0) or 0)
        price = float(item.get("Price per Hour (€)", 0) or 0)
        
        # Use values passed from UI (which might be manually edited)
        net_line = float(item.get("Total (€)", 0) or 0)
        tax_line = float(item.get("Tax 19% (€)", 0) or 0)
        
        if net_line == 0 and qty*price != 0: net_line = qty * price
        if tax_line == 0 and net_line != 0: tax_line = net_line * 0.19
        
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
