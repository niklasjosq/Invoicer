import datetime
from drafthorse.models.document import Document
from drafthorse.models.trade import TradeTransaction
from drafthorse.models.tradelines import LineItem
from drafthorse.models.party import SellerTradeParty, BuyerTradeParty
from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.note import IncludedNote

def generate_invoice_xml(data):
    """
    Generates ZUGFeRD XML from the provided data dictionary.
    data format expected:
    {
        "sender": {"name": str, ...},
        "recipient": {"name": str, ...},
        "items": [{"Description": str, "Quantity": float, "Price": float, "Tax": float}, ...],
        "id": str,
        "date": datetime.date
    }
    """
    doc = Document()
    doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931"
    
    # Header
    doc.header.id = data.get("id", "INV-001")
    # doc.header.name = "RECHNUNG"
    doc.header.type_code = "380" # Commercial Invoice
    doc.header.issue_date_time = data.get("date", datetime.date.today())
    
    # Trade Agreement
    doc.trade.agreement.seller.name = data["sender"].get("name", "Unknown Seller")
    # Map address lines to ZUGFeRD structure (simplified: just lines 1-3)
    seller_addr = data["sender"].get("address_lines", [])
    if len(seller_addr) > 0: doc.trade.agreement.seller.address.line_one = seller_addr[0]
    if len(seller_addr) > 1: doc.trade.agreement.seller.address.line_two = seller_addr[1]
    if len(seller_addr) > 2: doc.trade.agreement.seller.address.line_three = seller_addr[2]
    doc.trade.agreement.seller.address.country_id = "DE" # Defaulting to DE for now

    doc.trade.agreement.buyer.name = data["recipient"].get("name", "Unknown Buyer")
    buyer_addr = data["recipient"].get("address_lines", [])
    if len(buyer_addr) > 0: doc.trade.agreement.buyer.address.line_one = buyer_addr[0]
    if len(buyer_addr) > 1: doc.trade.agreement.buyer.address.line_two = buyer_addr[1]
    if len(buyer_addr) > 2: doc.trade.agreement.buyer.address.line_three = buyer_addr[2]
    doc.trade.agreement.buyer.address.country_id = "DE" 
    
    # Items and Totals
    total_net = 0.0
    total_tax = 0.0
    
    for item in data.get("items", []):
        li = LineItem()
        li.document.line_id = str(len(doc.trade.items.children) + 1)
        li.product.name = item.get("Description", "Item")
        
        # New keys from UI
        # We respect the Total provided by the UI (which handles calculation/manual override)
        net_line = float(item.get("Total (€)", 0) or 0)
        # Fallback if Total is 0 but Qty/Price exist (though UI handles this)
        qty = float(item.get("Quantity (hours)", 0) or 0)
        price = float(item.get("Price per Hour (€)", 0) or 0)
        if net_line == 0 and (qty * price) != 0:
             net_line = qty * price
             
        tax_amount = float(item.get("Tax 19% (€)", 0) or 0)  
        # We could recalc tax from net_line, but if user edited tax manually, we should use it?
        # For ZUGFeRD, consistency is key. standard is 19%.
        # If user edits Tax to be != 19% of Net, it might look weird unless we invoke a different tax category.
        # For now, let's keep the logic: use Net Line, and assume Tax is 19% of it for the XML tax details.
        # But wait, if user edited tax, we should probably output that tax amount?
        # Drafthorse calculates tax automatically generally or we set it?
        # In my code: `total_tax += net_line * (tax_percent / 100.0)`
        # This ignores manual tax edit.
        
        # Let's use the UI's values for totals
        if tax_amount == 0 and net_line != 0:
            tax_amount = net_line * 0.19
            
        tax_percent = 19.0 # We still claiming it's 19% VAT standard
        
        li.delivery.billed_quantity = (qty, "HUR") # HUR for Hours
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

    return doc.serialize(schema="FACTUR-X_EN16931").decode("utf-8")

from fpdf import FPDF
from drafthorse.pdf import attach_xml

def generate_invoice_pdf(data):
    """
    Generates visual PDF using fpdf2.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    
    # Title
    pdf.set_font("Helvetica", style="B", size=20)
    pdf.cell(0, 10, "RECHNUNG", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)
    
    # Details
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, f"Rechnungsnummer: {data.get('id', 'INV-001')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f"Datum: {data.get('date', datetime.date.today())}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    # Sender and Recipient
    col_width = pdf.epw / 2
    
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(col_width, 10, "Absender:", border=0)
    pdf.cell(col_width, 10, "Empfänger:", border=0, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font("Helvetica", size=12)
    
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
    
    # Table Header
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(70, 10, "Beschreibung", border=1)
    pdf.cell(30, 10, "Menge (Std)", border=1, align="R")
    pdf.cell(35, 10, "Preis/Std", border=1, align="R")
    pdf.cell(30, 10, "Netto", border=1, align="R")
    pdf.cell(25, 10, "Gesamt", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    # Table Rows
    pdf.set_font("Helvetica", size=12)
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
        
        pdf.cell(70, 10, desc, border=1)
        pdf.cell(30, 10, f"{qty:.2f}", border=1, align="R")
        pdf.cell(35, 10, f"{price:.2f}", border=1, align="R")
        pdf.cell(30, 10, f"{net_line:.2f}", border=1, align="R")
        pdf.cell(25, 10, f"{total_incl:.2f}", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        
    # Total
    total_gross = total_net + total_tax_accumulated
    
    pdf.ln(5)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(135, 10, "Summe Netto:", align="R")
    pdf.cell(55, 10, f"{total_net:.2f} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    pdf.cell(135, 10, "MwSt 19%:", align="R")
    pdf.cell(55, 10, f"{total_tax_accumulated:.2f} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    
    pdf.cell(135, 10, "Gesamtbetrag:", align="R")
    pdf.cell(55, 10, f"{total_gross:.2f} EUR", border=1, align="R", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def create_zugferd_pdf(pdf_bytes, xml_content):
    """
    Combines PDF and XML into ZUGFeRD PDF/A-3.
    """
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")
    
    output_pdf = attach_xml(pdf_bytes, xml_content, level="EN 16931")
    return output_pdf
