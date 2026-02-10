import streamlit as st
import datetime
import os
from io import StringIO
from invoice_logic import generate_invoice_xml, generate_invoice_pdf, create_zugferd_pdf
from streamlit_pdf_viewer import pdf_viewer

st.set_page_config(layout="wide", page_title="ZUGFeRD Invoice Generator")
st.title("ZUGFeRD Invoice Generator")

# Value defaults
DEFAULT_SENDER = "My Company GmbH"
DEFAULT_RECIPIENT = "Client Corp"
DEFAULT_ITEM = {"Description": "Consulting Services", "Quantity (hours)": 1.0, "Price per Hour (€)": 1.0}

import json

# --- History Helper Functions ---
HISTORY_FILE = "invoice_history.json"

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"senders": [], "recipients": [], "footers": []}
    try:
        with open(HISTORY_FILE, "r") as f:
            h = json.load(f)
            if "footers" not in h:
                h["footers"] = []
            return h
    except:
        return {"senders": [], "recipients": [], "footers": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def add_to_history(data):
    history = load_history()
    
    # Process Sender
    sender_entry = {
        "name_address": data["sender"].get("name", "") + "\n" + "\n".join(data["sender"].get("address_lines", [])),
        "tax_id": data.get("sender_tax_id", "")
    }
    # Check if exists (simple check by name_address)
    if sender_entry["name_address"].strip() and not any(s["name_address"] == sender_entry["name_address"] for s in history["senders"]):
        history["senders"].append(sender_entry)
        
    # Process Recipient
    recipient_entry = {
        "name_address": data["recipient"].get("name", "") + "\n" + "\n".join(data["recipient"].get("address_lines", [])),
        "customer_id": data.get("customer_id", "")
    }
    if recipient_entry["name_address"].strip() and not any(r["name_address"] == recipient_entry["name_address"] for r in history["recipients"]):
        history["recipients"].append(recipient_entry)
        
    # Process Footer
    footer_data = data.get("footer", {})
    footer_entry = {
        "col1": footer_data.get("col1", ""),
        "col2": footer_data.get("col2", ""),
        "col3": footer_data.get("col3", ""),
        "bank_name": footer_data.get("bank_name", ""),
        "iban": footer_data.get("iban", ""),
        "bic": footer_data.get("bic", "")
    }
    # Check if footer not empty and unique (check by strings in the 3 columns)
    if (footer_entry["col1"].strip() or footer_entry["col2"].strip() or footer_entry["col3"].strip()) and \
        not any(f["col1"] == footer_entry["col1"] and f["col2"] == footer_entry["col2"] and f["col3"] == footer_entry["col3"] for f in history["footers"]):
        history["footers"].append(footer_entry)
        
    save_history(history)

# --- Helper Functions ---

def get_next_invoice_id():
    """Reads and increments the invoice counter."""
    counter_file = ".invoice_counter"
    if not os.path.exists(counter_file):
        count = 1
    else:
        try:
            with open(counter_file, "r") as f:
                count = int(f.read().strip()) + 1
        except:
            count = 1
    return f"INV-2026-{count:03d}", count

def save_invoice_counter(count):
    """Saves the current invoice counter."""
    with open(".invoice_counter", "w") as f:
        f.write(str(count))

def clear_settings():
    """Resets all session state inputs to defaults."""
    st.session_state.sender_name = ""
    st.session_state.sender_tax = "" # Fixed key name to match text_input
    st.session_state.recipient_name = ""
    st.session_state.customer_id = "" # Fixed key name
    
    st.session_state.invoice_id_manual = get_next_invoice_id()[0] # Reset to next ID
    st.session_state.invoice_date = datetime.date.today()
    st.session_state.line_items_editor = [DEFAULT_ITEM]
    st.session_state.previous_line_items = [DEFAULT_ITEM]
    st.session_state.xml_content = None
    st.session_state.pdf_bytes = None
    st.session_state.zugferd_pdf = None
    st.session_state.qty_label = "Quantity (hours)"
    st.session_state.price_label = "Price per Hour (€)"
    st.session_state.unit_code = "HUR"
    st.session_state.footer_col1 = ""
    st.session_state.footer_col2 = ""
    st.session_state.footer_col3 = ""
    st.session_state.iban = ""
    st.session_state.bic = ""
    st.session_state.bank_name = ""
    st.session_state.contact_email = ""
    st.session_state.contact_phone = ""

# --- Initialization ---

if "xml_content" not in st.session_state:
    st.session_state.xml_content = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "zugferd_pdf" not in st.session_state:
    st.session_state.zugferd_pdf = None
if "qty_label" not in st.session_state:
    st.session_state.qty_label = "Quantity (hours)"
if "price_label" not in st.session_state:
    st.session_state.price_label = "Price per Hour (€)"
if "unit_code" not in st.session_state:
    st.session_state.unit_code = "HUR"
if "footer_col1" not in st.session_state:
    st.session_state.footer_col1 = ""
if "footer_col2" not in st.session_state:
    st.session_state.footer_col2 = ""
if "footer_col3" not in st.session_state:
    st.session_state.footer_col3 = ""

# Initialize ID if not present
if "invoice_id_manual" not in st.session_state:
     next_id, _ = get_next_invoice_id()
     st.session_state.invoice_id_manual = next_id

# Tabs Layout
tab_input, tab_xml, tab_pdf = st.tabs(["📝 Input Data", "📄 XML Preview", "👁️ PDF Preview"])

with tab_input:
    st.header("Input Data")
    
    # Load History
    history = load_history()
    
    # Clear Button
    if st.button("Clear All Settings", type="secondary"):
        clear_settings()
        st.rerun()

    col_details, col_dates = st.columns(2)
    
    with col_details:
        st.subheader("Sender")
        # Sender Selection
        sender_options = ["Select from History..."] + [s["name_address"].split('\n')[0] for s in history.get("senders", [])]
        
        def on_sender_change():
            idx = st.session_state.sender_select_idx
            if idx > 0:
                selected = history["senders"][idx-1] # -1 because of "Select..."
                st.session_state.sender_name = selected["name_address"]
                st.session_state.sender_tax = selected["tax_id"]

        st.selectbox(
            "Saved Senders", 
            options=range(len(sender_options)), 
            format_func=lambda x: sender_options[x],
            key="sender_select_idx",
            on_change=on_sender_change
        )

        sender_data = st.text_area("Sender Details (Name, Address)", height=100, key="sender_name", help="Line 1: Name\nOther lines: Address")
        sender_tax_id = st.text_input("Sender Tax ID / VAT ID (USt-IdNr.)", key="sender_tax")
        
        st.subheader("Recipient")
        # Recipient Selection
        recipient_options = ["Select from History..."] + [r["name_address"].split('\n')[0] for r in history.get("recipients", [])]
        
        def on_recipient_change():
            idx = st.session_state.recipient_select_idx
            if idx > 0:
                selected = history["recipients"][idx-1]
                st.session_state.recipient_name = selected["name_address"]
                st.session_state.customer_id = selected["customer_id"]

        st.selectbox(
            "Saved Recipients", 
            options=range(len(recipient_options)), 
            format_func=lambda x: recipient_options[x],
            key="recipient_select_idx",
            on_change=on_recipient_change
        )
        
        recipient_data = st.text_area("Recipient Details (Name, Address)", height=100, key="recipient_name", help="Line 1: Name\nOther lines: Address")
        customer_id = st.text_input("Customer ID (Kundennummer)", key="customer_id")
        
    with col_dates:
        invoice_id = st.text_input("Invoice Number", key="invoice_id_manual")
        invoice_date = st.date_input("Invoice Date", key="invoice_date", value=datetime.date.today())
        delivery_date = st.date_input("Service Date/Period (Leistungszeitraum)", key="delivery_date", value=(datetime.date.today(), datetime.date.today()))
        due_date = st.date_input("Due Date (Zahlungsziel)", key="due_date", value=datetime.date.today() + datetime.timedelta(days=14))
        invoice_subject = st.text_input("Subject / Reference", key="subject", value="Rechnung")
        
    with st.expander("Footer & Payment Details", expanded=False):
        # Footer Selection
        footer_options = ["Select from History..."] + [f"Footer Config {i+1}" for i in range(len(history.get("footers", [])))]
        
        def on_footer_change():
            idx = st.session_state.footer_select_idx
            if idx > 0:
                selected = history["footers"][idx-1]
                st.session_state.footer_col1 = selected["col1"]
                st.session_state.footer_col2 = selected["col2"]
                st.session_state.footer_col3 = selected["col3"]
                st.session_state.bank_name = selected["bank_name"]
                st.session_state.iban = selected["iban"]
                st.session_state.bic = selected["bic"]

        st.selectbox(
            "Saved Footers", 
            options=range(len(footer_options)), 
            format_func=lambda x: footer_options[x],
            key="footer_select_idx",
            on_change=on_footer_change
        )
        
        st.info("Write free text for the 3 columns in the PDF footer. Use the optional fields below if you need structured bank details for the ZUGFeRD XML.")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            st.text_area("Footer Column 1 (Left)", key="footer_col1", height=150, help="Typically: Sender Name, Address, Tax ID")
        with col_f2:
            st.text_area("Footer Column 2 (Middle)", key="footer_col2", height=150, help="Typically: Bank Name, IBAN, BIC")
        with col_f3:
            st.text_area("Footer Column 3 (Right)", key="footer_col3", height=150, help="Typically: Contact Email, Phone, Website")
            
        st.divider()
        st.subheader("Optional: XML Bank Details (Structured)")
        col_xml1, col_xml2, col_xml3 = st.columns(3)
        with col_xml1:
             st.text_input("Bank Name (XML)", key="bank_name")
        with col_xml2:
             st.text_input("IBAN (XML)", key="iban")
        with col_xml3:
             st.text_input("BIC (XML)", key="bic")
            
    with st.expander("⚙️ Columns & Units", expanded=False):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            st.text_input("Quantity Label", key="qty_label")
        with col_c2:
            st.text_input("Price Label", key="price_label")
        with col_c3:
            unit_options = {
                "HUR": "Hour (HUR)",
                "DAY": "Day (DAY)",
                "H87": "Piece (H87)",
                "C62": "Unit (C62)", 
                "LS": "Flat Rate (LS)",
                "KMT": "Kilometer (KMT)"
            }
            # Helper to find key by value or default
            st.selectbox(
                "Unit of Measure",
                options=list(unit_options.keys()),
                format_func=lambda x: unit_options[x],
                key="unit_code"
            )
        
    st.subheader("Line Items")
    
    # Load existing items or default
    if "line_items_editor" not in st.session_state or not st.session_state.line_items_editor:
         st.session_state.line_items_editor = [{"Description": "Consulting Services", "Quantity (hours)": 1.0, "Price per Hour (€)": 1.0, "Total (€)": 1.0, "Tax 19% (€)": 0.19, "Total incl. Tax (€)": 1.19}]

    if "previous_line_items" not in st.session_state:
        st.session_state.previous_line_items = st.session_state.line_items_editor

    # Data Editor with ENABLED columns
    edited_items = st.data_editor(
        st.session_state.line_items_editor,
        num_rows="dynamic",
        key="line_items_editor_widget",
        use_container_width=True,
        column_config={
            "Quantity (hours)": st.column_config.NumberColumn(label=st.session_state.qty_label, min_value=0, step=0.1, format="%.2f"),
            "Price per Hour (€)": st.column_config.NumberColumn(label=st.session_state.price_label, min_value=0, step=0.01, format="%.2f"),
            "Total (€)": st.column_config.NumberColumn(format="%.2f"), # Editable
            "Tax 19% (€)": st.column_config.NumberColumn(format="%.2f"), # Editable
            "Total incl. Tax (€)": st.column_config.NumberColumn(format="%.2f", disabled=True), # Gross still calculated for convenience or allow edit? Let's keep strict for now.
        }
    )

    # Smart Calculation Logic
    final_items = []
    has_changes = False
    
    # We iterate through edited_items. 
    # We attempt to match with previous_line_items by index.
    # Limitation: If rows are added/removed, index matching fails to correlate content. 
    # However, for simple edits, it works. New rows won't have a previous counterpart.
    
    previous_items = st.session_state.previous_line_items
    
    for i, item in enumerate(edited_items):
        # Get new values
        new_qty = float(item.get("Quantity (hours)", 0) or 0)
        new_price = float(item.get("Price per Hour (€)", 0) or 0)
        new_total = float(item.get("Total (€)", 0) or 0)
        new_tax = float(item.get("Tax 19% (€)", 0) or 0)
        
        # Get old values if they exist
        old_item = previous_items[i] if i < len(previous_items) else {}
        old_qty = float(old_item.get("Quantity (hours)", 0) or 0)
        old_price = float(old_item.get("Price per Hour (€)", 0) or 0)
        old_total = float(old_item.get("Total (€)", 0) or 0)
        old_tax = float(old_item.get("Tax 19% (€)", 0) or 0)
        
        # Default Logic variables
        final_total = new_total
        final_tax = new_tax
        
        # Change Detection
        # 1. Did Drivers (Qty/Price) change? -> Recalculate Total
        if abs(new_qty - old_qty) > 0.001 or abs(new_price - old_price) > 0.001:
            final_total = new_qty * new_price
            final_tax = final_total * 0.19
            
        # 2. Did Total change (manually)? -> Recalculate Tax
        elif abs(new_total - old_total) > 0.001:
            # User overrode Total. We accept it.
            # We recalculate Tax based on this new total.
            final_tax = final_total * 0.19
            
        # 3. Did Tax change (manually)? -> Accept it.
        # (Implicitly handled: final_tax is already new_tax)
        
        # 4. If nothing changed in inputs, but we have a mismatch in standard calc (e.g. initial load),
        # ensure consistency? No, respect what's there unless drivers trigger update.
        # But we MUST calculate Gross.
        
        final_incl = final_total + final_tax
        
        # Construct validated item
        new_item = item.copy()
        new_item["Total (€)"] = final_total
        new_item["Tax 19% (€)"] = final_tax
        new_item["Total incl. Tax (€)"] = final_incl
        
        final_items.append(new_item)
        
        # Check if we need to update state (if we changed values from what user typed/saw)
        if (abs(new_item["Total (€)"] - new_total) > 0.001 or 
            abs(new_item["Tax 19% (€)"] - new_tax) > 0.001):
            has_changes = True

    # Check for row deletion (if final_items shorter than previous, just update)
    if len(final_items) != len(previous_items):
        has_changes = True # State should sync to new list size

    # Update State if needed
    # We update both line_items_editor (for the widget) and previous_line_items (for next run)
    # Note: Updating line_items_editor triggers a rerun usually if we do it inside the script
    if has_changes:
        st.session_state.line_items_editor = final_items
        st.session_state.previous_line_items = final_items
        st.rerun()
    else:
        # Even if no visual changes, we must update previous_line_items to match current for next comparison
        # (e.g. if user just edited Qty, we handled it, now "old" must become "new")
        # Optimization: Only copy if different
        if final_items != previous_items:
             st.session_state.previous_line_items = final_items

    
    if st.button("Generate Invoice", type="primary"):
        # Save ID counter if it matches expected next
        current_next, current_count = get_next_invoice_id()
        if invoice_id == current_next:
             save_invoice_counter(current_count) 
        
        # Prepare Address Data
        # Split multi-line input
        def parse_address_block(text):
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            if not lines:
                return {"name": "", "address_lines": []}
            return {"name": lines[0], "address_lines": lines[1:]}

        sender_parsed = parse_address_block(sender_data)
        recipient_parsed = parse_address_block(recipient_data)

        # Gather data
        data = {
            "sender": sender_parsed,
            "sender_tax_id": sender_tax_id,
            
            "recipient": recipient_parsed,
            "customer_id": customer_id,
            
            "items": final_items,
            
            "id": invoice_id,
            "date": invoice_date,
            "delivery_date": delivery_date,
            "due_date": due_date,
            "subject": invoice_subject,
            
            "footer": {
                "col1": st.session_state.footer_col1,
                "col2": st.session_state.footer_col2,
                "col3": st.session_state.footer_col3,
                "bank_name": st.session_state.bank_name,
                "iban": st.session_state.iban,
                "bic": st.session_state.bic
            },
            
            "unit_code": st.session_state.unit_code
        }
        
        try:
            # Generate XML
            st.session_state.xml_content = generate_invoice_xml(data)
            
            # Generate Visual PDF
            st.session_state.pdf_bytes = generate_invoice_pdf(data)
            
            # Combine
            st.session_state.zugferd_pdf = create_zugferd_pdf(st.session_state.pdf_bytes, st.session_state.xml_content)
            
            # Save to History
            add_to_history(data)
            
            st.success("Invoice Generated! Check the Preview tabs.")
            
        except Exception as e:
            st.error(f"Error generating invoice: {e}")

with tab_xml:
    st.header("XML Preview")
    
    # File Uploader
    uploaded_xml = st.file_uploader("Upload XML", type=["xml"], help="Upload an existing Factur-X/ZUGFeRD XML file to replace the current content.")
    
    if uploaded_xml is not None:
        stringio = StringIO(uploaded_xml.getvalue().decode("utf-8"))
        read_xml = stringio.read()
        
        # Check if it differs to avoid loops (Streamlit logic) or just update if new upload
        # Simpler: If uploaded, we update state. Streamlit re-runs on upload.
        # We need to distinguish between "just uploaded" and "already processed".
        # We can use a session state key for the uploaded file ID, but simplest is just checking content diff.
        if read_xml != st.session_state.get("xml_content", ""):
            st.session_state.xml_content = read_xml
            # Auto-Sync
            if st.session_state.pdf_bytes:
                 try:
                    st.session_state.zugferd_pdf = create_zugferd_pdf(st.session_state.pdf_bytes, read_xml)
                    st.toast("XML Uploaded & Synced!", icon="✅")
                 except Exception as e:
                    st.error(f"Sync failed: {e}")
            else:
                 st.toast("XML Uploaded! Generate Invoice first to see PDF.", icon="ℹ️")

    if st.session_state.xml_content:
        # Editable XML
        xml_editor = st.text_area(
            "Edit XML Source", 
            value=st.session_state.xml_content, 
            height=600, 
            key="xml_editor_widget"
        )
        
        col_actions = st.columns([0.2, 0.8])
        
        with col_actions[0]:
            if st.button("🔄 Sync to PDF", help="Regenerate the PDF with your XML edits"):
                if xml_editor and st.session_state.pdf_bytes:
                    try:
                        # Re-create ZUGFeRD PDF with new XML
                        st.session_state.zugferd_pdf = create_zugferd_pdf(st.session_state.pdf_bytes, xml_editor)
                        st.session_state.xml_content = xml_editor
                        st.success("PDF synced!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Sync failed: {e}")
        
        with col_actions[1]:
            st.download_button(
                "Download XML",
                data=xml_editor,
                file_name="factur-x.xml",
                mime="text/xml"
            )
    else:
        st.info("Click 'Generate Invoice' or Upload XML to see content.")

with tab_pdf:
    st.header("PDF Preview")
    if st.session_state.zugferd_pdf:
        # Display PDF
        pdf_viewer(st.session_state.zugferd_pdf, width=800)
        
        st.download_button(
            "Download ZUGFeRD PDF",
            data=st.session_state.zugferd_pdf,
            file_name=f"{invoice_id}.pdf",
            mime="application/pdf"
        )
    elif st.session_state.pdf_bytes:
         pdf_viewer(st.session_state.pdf_bytes, width=800)
    else:
        st.info("Click 'Generate Invoice' to see the PDF.")

