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
DEFAULT_ITEM = {"Description": "Consulting Services", "Quantity (hours)": 10.0, "Price per Hour (€)": 150.0}

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
    st.session_state.recipient_name = ""
    st.session_state.invoice_id_manual = get_next_invoice_id()[0] # Reset to next ID
    st.session_state.invoice_date = datetime.date.today()
    st.session_state.line_items_editor = [DEFAULT_ITEM]
    st.session_state.previous_line_items = [DEFAULT_ITEM]
    st.session_state.xml_content = None
    st.session_state.pdf_bytes = None
    st.session_state.zugferd_pdf = None

# --- Initialization ---

if "xml_content" not in st.session_state:
    st.session_state.xml_content = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "zugferd_pdf" not in st.session_state:
    st.session_state.zugferd_pdf = None

# Initialize ID if not present
if "invoice_id_manual" not in st.session_state:
     next_id, _ = get_next_invoice_id()
     st.session_state.invoice_id_manual = next_id

# Initialize ID if not present
if "invoice_id_manual" not in st.session_state:
     next_id, _ = get_next_invoice_id()
     st.session_state.invoice_id_manual = next_id

# Tabs Layout
tab_input, tab_xml, tab_pdf = st.tabs(["📝 Input Data", "📄 XML Preview", "👁️ PDF Preview"])

with tab_input:
    st.header("Input Data")
    
    # Clear Button
    if st.button("Clear All Settings", type="secondary"):
        clear_settings()
        st.rerun()

    col_details, col_dates = st.columns(2)
    
    with col_details:
        sender_data = st.text_area("Sender Details (Name, Address)", height=100, key="sender_name", help="Line 1: Name\nOther lines: Address")
        recipient_data = st.text_area("Recipient Details (Name, Address)", height=100, key="recipient_name", help="Line 1: Name\nOther lines: Address")
        
    with col_dates:
        invoice_id = st.text_input("Invoice Number", key="invoice_id_manual")
        invoice_date = st.date_input("Invoice Date", key="invoice_date", value=datetime.date.today())
        
    st.subheader("Line Items")
    
    # Load existing items or default
    if "line_items_editor" not in st.session_state or not st.session_state.line_items_editor:
         st.session_state.line_items_editor = [{"Description": "Consulting Services", "Quantity (hours)": 10.0, "Price per Hour (€)": 150.0, "Total (€)": 1500.0, "Tax 19% (€)": 285.0, "Total incl. Tax (€)": 1785.0}]

    if "previous_line_items" not in st.session_state:
        st.session_state.previous_line_items = st.session_state.line_items_editor

    # Data Editor with ENABLED columns
    edited_items = st.data_editor(
        st.session_state.line_items_editor,
        num_rows="dynamic",
        key="line_items_editor_widget",
        use_container_width=True,
        column_config={
            "Quantity (hours)": st.column_config.NumberColumn(min_value=0, step=0.1, format="%.2f"),
            "Price per Hour (€)": st.column_config.NumberColumn(min_value=0, step=0.01, format="%.2f €"),
            "Total (€)": st.column_config.NumberColumn(format="%.2f €"), # Editable
            "Tax 19% (€)": st.column_config.NumberColumn(format="%.2f €"), # Editable
            "Total incl. Tax (€)": st.column_config.NumberColumn(format="%.2f €", disabled=True), # Gross still calculated for convenience or allow edit? Let's keep strict for now.
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
            "recipient": recipient_parsed,
            "items": final_items,
            "id": invoice_id,
            "date": invoice_date
        }
        
        try:
            # Generate XML
            st.session_state.xml_content = generate_invoice_xml(data)
            
            # Generate Visual PDF
            st.session_state.pdf_bytes = generate_invoice_pdf(data)
            
            # Combine
            st.session_state.zugferd_pdf = create_zugferd_pdf(st.session_state.pdf_bytes, st.session_state.xml_content)
            
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

