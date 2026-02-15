import streamlit as st
import datetime
import os
import json
from io import StringIO
from invoice_logic import generate_facturx_xml, generate_invoice_pdf, create_zugferd_pdf
from streamlit_pdf_viewer import pdf_viewer

st.set_page_config(layout="wide", page_title="ZUGFeRD Invoice Generator")
st.title("ZUGFeRD Invoice Generator")

# --- History Helper Functions ---
HISTORY_FILE = "invoice_history.json"

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"senders": [], "recipients": [], "footers": []}
    try:
        with open(HISTORY_FILE, "r") as f:
            h = json.load(f)
            # Ensure all keys exist
            if "senders" not in h: h["senders"] = []
            if "recipients" not in h: h["recipients"] = []
            if "footers" not in h: h["footers"] = []
            return h
    except:
        return {"senders": [], "recipients": [], "footers": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def add_to_history(data):
    history = load_history()
    
    # Save Sender
    sender_entry = {
        "name_address": data["sender"].get("name", "") + "\n" + "\n".join(data["sender"].get("address_lines", [])),
        "tax_id": data.get("sender_tax_id", "")
    }
    if sender_entry["name_address"].strip() and not any(s["name_address"] == sender_entry["name_address"] for s in history["senders"]):
        history["senders"].append(sender_entry)
        
    # Save Recipient
    recipient_entry = {
        "name_address": data["recipient"].get("name", "") + "\n" + "\n".join(data["recipient"].get("address_lines", [])),
        "customer_id": data.get("customer_id", "")
    }
    if recipient_entry["name_address"].strip() and not any(r["name_address"] == recipient_entry["name_address"] for r in history["recipients"]):
        history["recipients"].append(recipient_entry)
        
    # Save Footer
    footer = data.get("footer", {})
    footer_entry = {
        "iban": footer.get("iban", ""),
        "bic": footer.get("bic", ""),
        "col1": footer.get("col1", ""),
        "col2": footer.get("col2", ""),
        "col3": footer.get("col3", "")
    }
    # Save as history if IBAN is unique
    if footer_entry["iban"].strip() and not any(f["iban"] == footer_entry["iban"] for f in history["footers"]):
        history["footers"].append(footer_entry)
        
    save_history(history)

# Default values
DEFAULT_ITEM = {"name": "Consulting Services", "qty": 1.0, "price": 100.0, "vat_percent": 19.0}

if "xml_content" not in st.session_state:
    st.session_state.xml_content = None
if "zugferd_pdf" not in st.session_state:
    st.session_state.zugferd_pdf = None
if "line_items_list" not in st.session_state:
    st.session_state.line_items_list = [DEFAULT_ITEM.copy()]

tab_input, tab_xml, tab_pdf = st.tabs(["📝 Input Data", "📄 XML Preview", "👁️ PDF Preview"])

with tab_input:
    st.header("Input Data")
    
    history = load_history()
    
    col_s, col_r = st.columns(2)
    
    with col_s:
        st.subheader("Sender")
        sender_options = ["Select from History..."] + [s["name_address"].split('\n')[0] for s in history.get("senders", [])]
        def on_sender_change():
            idx = st.session_state.sender_select_idx
            if idx > 0:
                selected = history["senders"][idx-1]
                st.session_state.sender_name_area = selected["name_address"]
                st.session_state.sender_tax_id_in = selected["tax_id"]

        st.selectbox("History (Sender)", options=range(len(sender_options)), format_func=lambda x: sender_options[x], key="sender_select_idx", on_change=on_sender_change)
        s_name_addr = st.text_area("Name & Address", key="sender_name_area", value="My Company GmbH\nMain Street 1\n12345 Berlin")
        s_tax = st.text_input("VAT ID", key="sender_tax_id_in", value="DE123456789")
        
    with col_r:
        st.subheader("Recipient")
        recipient_options = ["Select from History..."] + [r["name_address"].split('\n')[0] for r in history.get("recipients", [])]
        def on_recipient_change():
            idx = st.session_state.recipient_select_idx
            if idx > 0:
                selected = history["recipients"][idx-1]
                st.session_state.recipient_name_area = selected["name_address"]
                st.session_state.customer_id_in = selected["customer_id"]

        st.selectbox("History (Recipient)", options=range(len(recipient_options)), format_func=lambda x: recipient_options[x], key="recipient_select_idx", on_change=on_recipient_change)
        r_name_addr = st.text_area("Name & Address", key="recipient_name_area", value="Client Corp\nSecond Street 2\n80331 Munich")
        r_cust = st.text_input("Customer ID", key="customer_id_in", value="CUST-001")

    st.subheader("Invoice Details")
    c1, c2, c3 = st.columns(3)
    inv_id = c1.text_input("Invoice Number", value="INV-2026-001")
    inv_date = c2.date_input("Invoice Date", value=datetime.date.today())
    due_date = c3.date_input("Due Date (BT-9)", value=inv_date + datetime.timedelta(days=14))
    
    c4, c5 = st.columns(2)
    project_id = c4.text_input("Project ID (BT-18)", value="", help="Internal project or object reference.")
    order_id = c5.text_input("Order ID (BT-13)", value="", help="Purchase order reference number.")
    
    st.subheader("Line Items")
    edited_items = st.data_editor(st.session_state.line_items_list, num_rows="dynamic", key="items_editor")
    st.session_state.line_items_list = edited_items 

    st.divider()
    st.subheader("Footer & Bank Details")
    
    footer_options = ["Select from History..."] + [f["iban"] for f in history.get("footers", [])]
    def on_footer_change():
        idx = st.session_state.footer_select_idx
        if idx > 0:
            selected = history["footers"][idx-1]
            st.session_state.iban_in = selected["iban"]
            st.session_state.bic_in = selected["bic"]
            st.session_state.f_col1 = selected["col1"]
            st.session_state.f_col2 = selected["col2"]
            st.session_state.f_col3 = selected["col3"]

    st.selectbox("History (Footer)", options=range(len(footer_options)), format_func=lambda x: footer_options[x], key="footer_select_idx", on_change=on_footer_change)
    
    f1, f2 = st.columns(2)
    iban = f1.text_input("IBAN", key="iban_in", value="DE12 3456 7890 1234 5678 90")
    bic = f2.text_input("BIC", key="bic_in", value="TESTDEFF")
    
    col1, col2, col3 = st.columns(3)
    f_col1 = col1.text_area("Footer Col 1 (Notes)", key="f_col1", value="Tax Office: Berlin-Mitte\nTax ID: 12/345/67890")
    f_col2 = col2.text_area("Footer Col 2 (Terms)", key="f_col2", value="Payment terms: 14 days net.\nPlease transfer to IBAN listed.")
    f_col3 = col3.text_area("Footer Col 3 (Contact)", key="f_col3", value="Email: info@mycompany.de\nPhone: +49 30 123456")

    if st.button("Generate Invoice", type="primary"):
        s_parts = [l.strip() for l in s_name_addr.split("\n") if l.strip()]
        r_parts = [l.strip() for l in r_name_addr.split("\n") if l.strip()]
        
        data = {
            "id": inv_id,
            "date": inv_date,
            "due_date": due_date,
            "project_id": project_id,
            "order_id": order_id,
            "sender": {
                "name": s_parts[0] if s_parts else "Seller",
                "address_lines": s_parts[1:]
            },
            "sender_tax_id": s_tax,
            "recipient": {
                "name": r_parts[0] if r_parts else "Buyer",
                "address_lines": r_parts[1:]
            },
            "customer_id": r_cust,
            "items": edited_items,
            "footer": {
                "iban": iban,
                "bic": bic,
                "col1": f_col1,
                "col2": f_col2,
                "col3": f_col3
            },
            "unit_code": "C62"
        }
        
        try:
            st.session_state.xml_content = generate_facturx_xml(data)
            pdf_bytes = generate_invoice_pdf(data)
            st.session_state.zugferd_pdf = create_zugferd_pdf(pdf_bytes, st.session_state.xml_content)
            add_to_history(data)
            st.success("Invoice generated successfully!")
        except Exception as e:
            st.error(f"Error: {e}")

with tab_xml:
    st.header("XML Preview")
    if st.session_state.xml_content:
        st.code(st.session_state.xml_content, language="xml")
        st.download_button("Download XML", st.session_state.xml_content, "factur-x.xml", "text/xml")

with tab_pdf:
    st.header("PDF Preview")
    if st.session_state.zugferd_pdf:
        pdf_viewer(st.session_state.zugferd_pdf, width=800)
        st.download_button("Download ZUGFeRD PDF", st.session_state.zugferd_pdf, f"{inv_id}.pdf", "application/pdf")
