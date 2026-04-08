import streamlit as st
import datetime
import os
import json
from io import StringIO
from dotenv import load_dotenv
from invoice_logic import generate_facturx_xml, generate_invoice_pdf, create_zugferd_pdf
from accounting_logic import (
    extract_data_from_pdf,
    generate_ustva_xml,
    generate_euer_xml,
    extract_data_from_xml_file,
    calculate_ustva_totals,
    KATEGORIE_MAPPING,
)
from streamlit_pdf_viewer import pdf_viewer

load_dotenv()

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

# --- Accounting Helper Functions ---
TRANSACTIONS_FILE = "transactions.json"

def load_transactions():
    if not os.path.exists(TRANSACTIONS_FILE):
        return []
    try:
        with open(TRANSACTIONS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_transactions(data):
    with open(TRANSACTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4, default=str)

def add_transaction(t):
    ts = load_transactions()
    # Prevent duplicate invoice IDs
    if t.get("id") and any(existing["id"] == t["id"] for existing in ts):
        return False
    ts.append(t)
    save_transactions(ts)
    return True

# --- Invoice Counter ---
COUNTER_FILE = ".invoice_counter"

def load_counter():
    if not os.path.exists(COUNTER_FILE):
        return 1
    try:
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return 1

def save_counter(val):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(val))

def next_invoice_id(inv_date, recipient_name):
    """Generate INV-YYYY-MM-DD-NNN_Customer format.
    Counter uses minimum 3 digits but grows naturally (001...999, 1000, 1001...).
    """
    counter = load_counter()
    # Sanitize customer name: first word, alphanumeric only
    customer = recipient_name.split("\n")[0].strip().split()[0] if recipient_name.strip() else "Customer"
    customer = "".join(c for c in customer if c.isalnum() or c in "-_")
    date_str = inv_date.strftime("%Y-%m-%d")
    counter_str = str(counter).zfill(3)  # min 3 digits, grows beyond 999 naturally
    inv_id = f"INV-{date_str}-{counter_str}_{customer}"
    return inv_id, counter

# Default values
DEFAULT_ITEM = {"name": "Consulting Services", "qty": 1.0, "price": 100.0, "vat_percent": 19.0}

if "xml_content" not in st.session_state:
    st.session_state.xml_content = None
if "zugferd_pdf" not in st.session_state:
    st.session_state.zugferd_pdf = None
if "line_items_list" not in st.session_state:
    st.session_state.line_items_list = [DEFAULT_ITEM.copy()]

tab_input, tab_xml, tab_pdf, tab_scanner, tab_ustva, tab_euer = st.tabs(["📝 Input Data", "📄 XML Preview", "👁️ PDF Preview", "📂 Scanner", "📈 UStVA", "📊 EÜR (Jährlich)"])

with tab_input:
    st.header("Input Data")

    history = load_history()

    # Initialize widget defaults in session state (once)
    _defaults = {
        "sender_name_area": "My Company GmbH\nMain Street 1\n12345 Berlin",
        "sender_tax_id_in": "DE123456789",
        "recipient_name_area": "Client Corp\nSecond Street 2\n80331 Munich",
        "customer_id_in": "CUST-001",
        "iban_in": "DE12 3456 7890 1234 5678 90",
        "bic_in": "TESTDEFF",
        "f_col1": "Tax Office: Berlin-Mitte\nTax ID: 12/345/67890",
        "f_col2": "Payment terms: 14 days net.\nPlease transfer to IBAN listed.",
        "f_col3": "Email: info@mycompany.de\nPhone: +49 30 123456",
    }
    for _k, _v in _defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

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
        s_name_addr = st.text_area("Name & Address", key="sender_name_area")
        s_tax = st.text_input("VAT ID", key="sender_tax_id_in")
        
        st.markdown("---")
        st.write("Firmenlogo (Rechts oben)")
        uploaded_logo = st.file_uploader("Logo hochladen (PNG)", type="png", key="logo_uploader")
        
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir)
            
        logo_path = os.path.join(assets_dir, "logo.png")
        
        if uploaded_logo is not None:
            with open(logo_path, "wb") as f:
                f.write(uploaded_logo.getbuffer())
            st.success("Logo gespeichert!")
        
        if os.path.exists(logo_path):
            st.image(logo_path, width=100)
        
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
        r_name_addr = st.text_area("Name & Address", key="recipient_name_area")
        r_cust = st.text_input("Customer ID", key="customer_id_in")

    st.subheader("Invoice Details")
    c1, c2, c3 = st.columns(3)
    inv_date = c2.date_input("Invoice Date", value=datetime.date.today())
    due_date = c3.date_input("Due Date (BT-9)", value=inv_date + datetime.timedelta(days=14))

    # Auto-generate invoice ID from date + counter + customer name
    auto_id, _counter_val = next_invoice_id(inv_date, r_name_addr)
    inv_id = c1.text_input("Invoice Number", value=auto_id,
                           help="Format: INV-YYYY-MM-DD-NNN_Customer. Auto-generated, editable.")
    
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
    iban = f1.text_input("IBAN", key="iban_in")
    bic = f2.text_input("BIC", key="bic_in")

    col1, col2, col3 = st.columns(3)
    f_col1 = col1.text_area("Footer Col 1 (Notes)", key="f_col1")
    f_col2 = col2.text_area("Footer Col 2 (Terms)", key="f_col2")
    f_col3 = col3.text_area("Footer Col 3 (Contact)", key="f_col3")

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
            "unit_code": "C62",
            "logo_path": logo_path if os.path.exists(logo_path) else None
        }

        # Calculate totals for accounting
        total_net = 0.0
        total_tax = 0.0
        for item in edited_items:
            q = float(item.get("qty", item.get("Quantity (hours)", 0)) or 0)
            p = float(item.get("price", item.get("Price per Hour (€)", 0)) or 0)
            v = float(item.get("vat_percent", 19.0))
            net = q * p
            tax = net * (v / 100.0)
            total_net += net
            total_tax += tax
            
        grand_total = total_net + total_tax
        
        try:
            st.session_state.xml_content = generate_facturx_xml(data)
            pdf_bytes = generate_invoice_pdf(data)
            st.session_state.zugferd_pdf = create_zugferd_pdf(pdf_bytes, st.session_state.xml_content)
            add_to_history(data)

            # Increment counter for next invoice
            save_counter(_counter_val + 1)
            st.session_state.last_inv_id = inv_id

            # Hook: Add to transactions
            # Determine category based on tax rate
            # Heuristic: 19% = Umsatzerlöse (Dienstleistungen) 19%, 7% = Umsatzerlöse (Dienstleistungen) 7%
            # Default to "Dienstleistungen" since distinguishing Waren vs. Dienste requires manual review
            cat = "Aus: Umsatzerlöse (Dienstleistungen) 19%"
            if total_net > 0:
                eff_rate = total_tax / total_net
                if 0.06 < eff_rate < 0.08:
                    cat = "Aus: Umsatzerlöse (Dienstleistungen) 7%"
                elif eff_rate < 0.01:
                    # Tax-free output - choose tax-free category (no output tax to report)
                    cat = "Aus: Umsatzerlöse (Dienstleistungen) 7%"  # Placeholder - user can adjust

            new_tx = {
                "id": inv_id,
                "date": inv_date.strftime("%Y-%m-%d"),
                "partner": r_parts[0] if r_parts else "Buyer",
                "net_amount": round(total_net, 2),
                "tax_amount": round(total_tax, 2),
                "gross_amount": round(grand_total, 2),
                "type": "Einnahme",
                "payment_date": None, # Unpaid initially
                "category": cat
            }
            add_transaction(new_tx)

            st.success("Invoice generated successfully and added to Accounting!")
        except Exception as e:
            st.error(f"Error: {e}")

with tab_xml:
    st.header("XML Preview")
    if st.session_state.xml_content:
        dl_id = st.session_state.get("last_inv_id", inv_id)
        st.code(st.session_state.xml_content, language="xml")
        st.download_button("Download XML", st.session_state.xml_content, f"{dl_id}.xml", "text/xml")

with tab_pdf:
    st.header("PDF Preview")
    if st.session_state.zugferd_pdf:
        dl_id = st.session_state.get("last_inv_id", inv_id)
        pdf_viewer(st.session_state.zugferd_pdf, width=800)
        st.download_button("Download ZUGFeRD PDF", st.session_state.zugferd_pdf, f"{dl_id}.pdf", "application/pdf")

with tab_scanner:
    st.header("📂 Invoice Scanner")

    # Initialize session state for scanned invoices
    if "scanned_invoices" not in st.session_state:
        st.session_state.scanned_invoices = []
    if "scan_skipped" not in st.session_state:
        st.session_state.scan_skipped = []

    # Directory input
    default_dir = os.getenv("INVOICE_DIRECTORY", ".")
    invoice_dir = st.text_input("Invoice Directory", value=default_dir)

    if st.button("🔍 Scan Directory", type="primary"):
        if not os.path.exists(invoice_dir):
            st.error("Directory not found!")
        else:
            # Collect files, deduplicate by filename stem (prefer PDF over XML)
            all_files = {}
            for scan_root, dirs, files in os.walk(invoice_dir):
                for file in files:
                    if file.lower().endswith((".pdf", ".xml")):
                        stem = os.path.splitext(file)[0]
                        fpath_candidate = os.path.join(scan_root, file)
                        if stem not in all_files or file.lower().endswith(".pdf"):
                            all_files[stem] = fpath_candidate
            found_files = list(all_files.values())

            st.info(f"Found {len(found_files)} unique invoice files.")

            scanned = []
            skipped = []
            current_txs = load_transactions()
            current_ids = {t["id"] for t in current_txs}

            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, fpath in enumerate(found_files):
                status_text.text(f"Processing {os.path.basename(fpath)}...")
                data = None

                if fpath.lower().endswith(".pdf"):
                    data = extract_data_from_pdf(fpath)
                elif fpath.lower().endswith(".xml"):
                    data = extract_data_from_xml_file(fpath)

                if data:
                    if data["id"] and data["id"] not in current_ids:
                        data["_import"] = True  # Checkbox default
                        data["_source"] = os.path.basename(fpath)
                        scanned.append(data)
                        current_ids.add(data["id"])
                    else:
                        skipped.append({"file": os.path.basename(fpath), "id": data.get("id", "?"), "reason": "Already imported"})

                progress_bar.progress((i + 1) / len(found_files))

            status_text.text("Scan complete!")
            st.session_state.scanned_invoices = scanned
            st.session_state.scan_skipped = skipped

    # Show skipped files
    if st.session_state.scan_skipped:
        with st.expander(f"⏭️ Skipped {len(st.session_state.scan_skipped)} duplicates"):
            st.dataframe(st.session_state.scan_skipped, use_container_width=True)

    # Interactive review table
    if st.session_state.scanned_invoices:
        st.subheader(f"📋 Review {len(st.session_state.scanned_invoices)} scanned invoices")
        st.info("Review and adjust categories, set payment dates, then import selected invoices.")

        scanner_col_config = {
            "_import": st.column_config.CheckboxColumn("Import", default=True),
            "_source": st.column_config.TextColumn("Source File", disabled=True),
            "id": st.column_config.TextColumn("Invoice Nr.", disabled=True),
            "date": st.column_config.TextColumn("Invoice Date", disabled=True),
            "partner": st.column_config.TextColumn("Partner", disabled=True),
            "net_amount": st.column_config.NumberColumn("Net (€)", format="%.2f €", disabled=True),
            "tax_amount": st.column_config.NumberColumn("VAT (€)", format="%.2f €", disabled=True),
            "gross_amount": st.column_config.NumberColumn("Gross (€)", format="%.2f €", disabled=True),
            "type": st.column_config.SelectboxColumn("Type", options=["Einnahme", "Ausgabe"], required=True),
            "payment_date": st.column_config.DateColumn(
                "Payment Date",
                format="DD.MM.YYYY",
                help="Set when paid to include in UStVA",
                min_value=datetime.date(2020, 1, 1),
                max_value=datetime.date(2030, 12, 31),
            ),
            "category": st.column_config.SelectboxColumn(
                "Category",
                options=list(KATEGORIE_MAPPING.keys()),
                required=True,
            ),
            "vat_id": st.column_config.TextColumn("VAT ID", disabled=True),
        }

        column_order = ["_import", "_source", "id", "date", "partner", "net_amount", "tax_amount",
                        "gross_amount", "type", "payment_date", "category"]

        edited_scanned = st.data_editor(
            st.session_state.scanned_invoices,
            key="scanner_editor",
            num_rows="fixed",
            use_container_width=True,
            column_config=scanner_col_config,
            column_order=column_order,
        )

        col_import, col_clear = st.columns([1, 1])

        with col_import:
            if st.button("✅ Import Selected", type="primary"):
                to_import = [t for t in edited_scanned if t.get("_import", False)]
                if not to_import:
                    st.warning("No invoices selected for import.")
                else:
                    current_txs = load_transactions()
                    current_ids = {t["id"] for t in current_txs}
                    imported = 0
                    for t in to_import:
                        # Remove internal fields before saving
                        tx = {k: v for k, v in t.items() if not k.startswith("_")}
                        if tx["id"] not in current_ids:
                            current_txs.append(tx)
                            current_ids.add(tx["id"])
                            imported += 1
                    save_transactions(current_txs)
                    st.success(f"Imported {imported} invoices!")
                    st.session_state.scanned_invoices = []
                    st.session_state.scan_skipped = []
                    st.rerun()

        with col_clear:
            if st.button("🗑️ Clear Scan Results"):
                st.session_state.scanned_invoices = []
                st.session_state.scan_skipped = []
                st.rerun()
    elif not st.session_state.scanned_invoices:
        st.caption("Scan a directory to find and review invoices before importing.")

with tab_ustva:
    st.header("UStVA")

    QUARTER_MONTHS = {1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9], 4: [10, 11, 12]}
    QUARTER_ZEITRAUM = {1: "41", 2: "42", 3: "43", 4: "44"}

    col_u0, col_u1, col_u2 = st.columns([1, 1, 1])
    ustva_mode = col_u0.radio("Voranmeldungszeitraum", ["Monatlich", "Vierteljährlich"], key="ustva_mode", horizontal=True)
    sel_year = col_u1.number_input("Jahr", 2020, 2030, datetime.date.today().year, key="ustva_year")

    if ustva_mode == "Monatlich":
        sel_month = col_u2.selectbox("Monat", range(1, 13), index=datetime.date.today().month - 1, key="ustva_month")
        sel_months = [sel_month]
        sel_zeitraum = f"{sel_month:02d}"
        period_label = f"{sel_month:02d}/{sel_year}"
    else:
        current_quarter = (datetime.date.today().month - 1) // 3 + 1
        sel_quarter = col_u2.selectbox("Quartal", [1, 2, 3, 4], index=current_quarter - 1, key="ustva_quarter", format_func=lambda q: f"Q{q} ({QUARTER_MONTHS[q][0]:02d}-{QUARTER_MONTHS[q][-1]:02d})")
        sel_months = QUARTER_MONTHS[sel_quarter]
        sel_zeitraum = QUARTER_ZEITRAUM[sel_quarter]
        period_label = f"Q{sel_quarter}/{sel_year}"

    st.markdown("### Steuerfall (Unternehmer)")

    ustva_history = load_history()
    ustva_sender_options = ["Aus History wählen..."] + [
        s["name_address"].split("\n")[0] for s in ustva_history.get("senders", [])
    ]

    def on_ustva_sender_change():
        idx = st.session_state.ustva_sender_select_idx
        if idx > 0:
            selected = ustva_history["senders"][idx - 1]
            lines = [l.strip() for l in selected["name_address"].split("\n") if l.strip()]
            st.session_state.ustva_name = lines[0] if lines else ""
            st.session_state.ustva_strasse = lines[1] if len(lines) > 1 else ""
            # Parse "PLZ Ort" from address line
            if len(lines) > 2:
                plz_ort = lines[2]
                parts = plz_ort.split(" ", 1)
                if len(parts) == 2 and parts[0].isdigit():
                    st.session_state.ustva_plz = parts[0]
                    st.session_state.ustva_ort = parts[1]
                else:
                    st.session_state.ustva_plz = ""
                    st.session_state.ustva_ort = plz_ort
            st.session_state.ustva_stnr = selected.get("tax_id", "")

    st.selectbox(
        "History (Absender)",
        options=range(len(ustva_sender_options)),
        format_func=lambda x: ustva_sender_options[x],
        key="ustva_sender_select_idx",
        on_change=on_ustva_sender_change,
    )

    col_tax_1, col_tax_2, col_tax_3 = st.columns(3)
    ustva_stnr = col_tax_1.text_input(
        "Steuernummer (13-stellig, Bundesschema)",
        key="ustva_stnr",
        help="ELSTER erfordert die 13-stellige Bundeseinheitliche Steuernummer, z.B. 2614082562547. Zu finden in Mein ELSTER oder auf dem Steuerbescheid.",
    )
    ustva_name = col_tax_2.text_input("Nachname/Firmenname", key="ustva_name")
    ustva_vorname = col_tax_3.text_input("Vorname", key="ustva_vorname")

    stnr_digits = "".join(c for c in ustva_stnr if c.isdigit())
    if ustva_stnr and len(stnr_digits) != 13:
        st.warning(f"Steuernummer hat {len(stnr_digits)} Ziffern — ELSTER erfordert genau 13 (Bundesschema).")

    st.markdown("### Adresse (DatenLieferant)")
    col_addr1, col_addr2, col_addr3 = st.columns(3)
    ustva_strasse = col_addr1.text_input("Straße", key="ustva_strasse")
    ustva_plz = col_addr2.text_input("PLZ", key="ustva_plz")
    ustva_ort = col_addr3.text_input("Ort", key="ustva_ort")
    
    st.markdown("### Eingangsrechnungen hochladen")
    uploaded_files = st.file_uploader("ZUGFeRD/XRechnung PDFs", accept_multiple_files=True, type="pdf")
    
    if uploaded_files:
        if st.button("Verarbeite Uploads"):
            new_txs = []
            current_txs = load_transactions()
            current_ids = [t["id"] for t in current_txs]
            
            for uf in uploaded_files:
                data = extract_data_from_pdf(uf.getvalue())
                if data:
                    if data["id"] not in current_ids:
                        new_txs.append(data)
                        current_ids.append(data["id"])
                    else:
                        st.warning(f"Rechnung {data['id']} bereits vorhanden.")
                else:
                    st.error(f"Konnte keine ZUGFeRD Daten aus {uf.name} lesen.")
            
            if new_txs:
                current_txs.extend(new_txs)
                save_transactions(current_txs)
                st.success(f"{len(new_txs)} Rechnungen hinzugefügt.")
                st.rerun()

    st.markdown("### Eingangsrechnung manuell erfassen")
    st.caption("Für Rechnungen ohne ZUGFeRD/XRechnung XML (einfache PDFs).")

    eingangs_categories = [k for k, v in KATEGORIE_MAPPING.items() if v["type"] == "Ausgabe"]

    with st.form("manual_eingang_form"):
        col_m1, col_m2, col_m3 = st.columns(3)
        m_id = col_m1.text_input("Rechnungs-Nr.")
        m_date = col_m2.date_input("Rechnungsdatum", value=datetime.date.today())
        m_partner = col_m3.text_input("Partner / Lieferant")

        col_m4, col_m5, col_m6 = st.columns(3)
        m_net = col_m4.number_input("Netto (€)", min_value=0.0, step=0.01, format="%.2f")
        m_tax = col_m5.number_input("MwSt (€)", min_value=0.0, step=0.01, format="%.2f")
        m_gross = col_m6.number_input("Brutto (€)", min_value=0.0, step=0.01, format="%.2f")

        col_m7, col_m8 = st.columns(2)
        m_category = col_m7.selectbox("Kategorie", options=eingangs_categories)
        m_payment_date = col_m8.date_input("Zahldatum (optional)", value=None)

        submitted = st.form_submit_button("Eingangsrechnung hinzufügen")
        if submitted:
            if not m_id:
                st.error("Bitte eine Rechnungs-Nr. angeben.")
            elif m_net <= 0 and m_gross <= 0:
                st.error("Bitte mindestens Netto- oder Bruttobetrag angeben.")
            else:
                manual_tx = {
                    "id": m_id,
                    "date": m_date.strftime("%Y-%m-%d"),
                    "partner": m_partner,
                    "net_amount": m_net,
                    "tax_amount": m_tax,
                    "gross_amount": m_gross,
                    "type": "Ausgabe",
                    "payment_date": m_payment_date.strftime("%Y-%m-%d") if m_payment_date else None,
                    "category": m_category,
                    "vat_id": "",
                }
                if add_transaction(manual_tx):
                    st.success(f"Rechnung {m_id} hinzugefügt.")
                    st.rerun()
                else:
                    st.warning(f"Rechnung {m_id} bereits vorhanden.")

    st.markdown("### Transaktionen bearbeiten")
    st.info("Setze das 'Payment Date', um die Rechnung in die UStVA/EÜR aufzunehmen.")
    
    transactions = load_transactions()
    
    # Pre-process for editor
    for t in transactions:
        # Date conversions
        if t.get("payment_date"):
            try:
                if isinstance(t["payment_date"], str):
                    t["payment_date"] = datetime.datetime.strptime(t["payment_date"], "%Y-%m-%d").date()
            except:
                t["payment_date"] = None
        
        if t.get("date"):
            try:
                if isinstance(t["date"], str):
                    t["date"] = datetime.datetime.strptime(t["date"], "%Y-%m-%d").date()
            except:
                pass

        # Auto-Correct Type based on Category
        # If category starts with "Ein:" -> Force Type "Ausgabe"
        # If category starts with "Aus:" -> Force Type "Einnahme"
        cat = t.get("category", "")
        if cat and isinstance(cat, str):
            if cat.startswith("Ein:"):
                t["type"] = "Ausgabe"
            elif cat.startswith("Aus:"):
                t["type"] = "Einnahme"
    
    # Helper function to get category options by type
    def get_category_options(tx_type):
        # We allow ALL options in dropdown to enable fixing wrong categories
        return list(KATEGORIE_MAPPING.keys())
    
    # Shared column config for both editors
    def make_tx_col_config():
        return {
            "id": st.column_config.TextColumn("Rechnungs-Nr."),
            "date": st.column_config.DateColumn("Rechnungsdatum", format="DD.MM.YYYY"),
            "partner": st.column_config.TextColumn("Partner"),
            "net_amount": st.column_config.NumberColumn("Netto (€)", format="%.2f €"),
            "tax_amount": st.column_config.NumberColumn("MwSt (€)", format="%.2f €"),
            "gross_amount": st.column_config.NumberColumn("Brutto (€)", format="%.2f €"),
            "type": st.column_config.SelectboxColumn("Typ", options=["Einnahme", "Ausgabe"], required=True),
            "payment_date": st.column_config.DateColumn(
                "Zahldatum",
                format="DD.MM.YYYY",
                help="Wann wurde die Rechnung bezahlt?",
                min_value=datetime.date(2020, 1, 1),
                max_value=datetime.date(2030, 12, 31),
                step=1
            ),
            "category": st.column_config.SelectboxColumn(
                "Kategorie (ELSTER)",
                options=list(KATEGORIE_MAPPING.keys()),
                help="Wähle die passende Kategorie",
                required=True
            ),
        }

    # Separate data editors for Einnahmen (Ausgangsrechnungen) and Ausgaben (Eingangsrechnungen)
    st.subheader("📤 Ausgangsrechnungen (Einnahmen)")
    st.caption("Zeilen auswählen und mit Entf/Delete löschen. Kategorien und alle Felder sind editierbar.")
    ausgangs_txs = [t for t in transactions if t.get("type") == "Einnahme"]

    edited_ausgangs = st.data_editor(
        ausgangs_txs,
        key="ausgangs_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config=make_tx_col_config(),
    )

    st.subheader("📥 Eingangsrechnungen (Ausgaben)")
    st.caption("Zeilen auswählen und mit Entf/Delete löschen. Kategorien und alle Felder sind editierbar.")
    eingangs_txs = [t for t in transactions if t.get("type") == "Ausgabe"]

    edited_eingangs = st.data_editor(
        eingangs_txs,
        key="eingangs_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config=make_tx_col_config(),
    )
    
    # Catch-all for transactions with missing/wrong type
    other_txs = [t for t in transactions if t.get("type") not in ["Einnahme", "Ausgabe"]]
    if other_txs:
        st.subheader("⚠️ Nicht zugeordnete Transaktionen")
        st.warning("Bitte weisen Sie diesen Transaktionen einen Typ zu.")
        edited_other = st.data_editor(
            other_txs,
            key="other_editor",
            column_config={
                "type": st.column_config.SelectboxColumn("Typ", options=["Einnahme", "Ausgabe"], required=True),
                "category": st.column_config.SelectboxColumn("Kategorie", options=list(KATEGORIE_MAPPING.keys()))
            }
        )
        # Merge all
        edited_txs = edited_ausgangs + edited_eingangs + edited_other
    else:
        edited_txs = edited_ausgangs + edited_eingangs
    
    if st.button("Änderungen speichern"):
        # Post-process for JSON
        to_save = []
        for t in edited_txs:
            t_copy = t.copy()
            if t_copy.get("payment_date") and isinstance(t_copy["payment_date"], (datetime.date, datetime.datetime)):
                t_copy["payment_date"] = t_copy["payment_date"].strftime("%Y-%m-%d")
            
            if t_copy.get("date") and isinstance(t_copy["date"], (datetime.date, datetime.datetime)):
                t_copy["date"] = t_copy["date"].strftime("%Y-%m-%d")
                
            to_save.append(t_copy)
        save_transactions(to_save)
        st.success("Gespeichert!")
        transactions = edited_txs # Update local var for calculation below
        
    # Calculate UStVA metrics
    # Filter by Payment Date in selected Month/Year
    ustva_xml = generate_ustva_xml(
        edited_txs,
        sel_months,
        sel_year,
        zeitraum=sel_zeitraum,
        stnr=ustva_stnr,
        name=ustva_name,
        vorname=ustva_vorname,
        strasse=ustva_strasse,
        plz=ustva_plz,
        ort=ustva_ort,
    )

    # Calculate UStVA metrics matching ELSTER logic
    totals = calculate_ustva_totals(edited_txs, sel_months, sel_year)
    count_relevant = totals["count_relevant"]
    kz_base_sums = totals["kz_base_sums"]
    kz_input_tax_sums = totals["kz_input_tax_sums"]
    sum_sales_vat = totals["sum_sales_vat"]
    sum_input_tax = totals["sum_input_tax"]
    zahllast = totals["zahllast"]
    
    st.caption(f"Berechnungsgrundlage: {count_relevant} Buchungen im Zeitraum {period_label}.")
    # Debug info (can be removed later)
    if count_relevant > 0 and sum_sales_vat == 0 and sum_input_tax == 0:
        st.warning("Keine Steuer berechnet. Prüfe Kategorien:")
        st.write("Erkannte Basis-Summen (KZ):", kz_base_sums)
        st.write("Erkannte Vorsteuer-Summen (KZ):", kz_input_tax_sums)
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Umsatzsteuer (Einnahmen)", f"{sum_sales_vat:.2f} €")
    m2.metric("Vorsteuer (Ausgaben)", f"{sum_input_tax:.2f} €")
    m3.metric("Zahllast", f"{zahllast:.2f} €", delta_color="inverse")
    st.caption("Hinweis: Die Umsatzsteuer wird aus der auf volle EUR abgerundeten Bemessungsgrundlage (Kz 81/86/89) berechnet, nicht aus der Summe der einzelnen MwSt-Beträge. Geringe Abweichungen sind ELSTER-konform.")

    # Visual UStVA form preview matching official USt 1 A
    kz_base_rounded = totals["kz_base_rounded"]
    with st.expander("📋 UStVA Formular (Vorschau)", expanded=False):
        st.caption(f"Voranmeldungszeitraum: {period_label}")

        # Section A: Steuerpflichtige Umsätze
        base_81 = kz_base_rounded.get("81", 0)
        base_86 = kz_base_rounded.get("86", 0)
        base_87 = kz_base_rounded.get("87", 0)
        if base_81 or base_86 or base_87:
            st.markdown("**A. Steuerpflichtige Lieferungen und sonstige Leistungen**")
            form_a = []
            if base_81:
                form_a.append({"Zeile": 13, "Beschreibung": "zum Steuersatz von 19 %", "Kz": 81,
                               "Bemessungsgrundlage (€)": f"{base_81:,}", "Steuer (€)": f"{base_81 * 0.19:.2f}"})
            if base_86:
                form_a.append({"Zeile": 14, "Beschreibung": "zum Steuersatz von 7 %", "Kz": 86,
                               "Bemessungsgrundlage (€)": f"{base_86:,}", "Steuer (€)": f"{base_86 * 0.07:.2f}"})
            if base_87:
                form_a.append({"Zeile": 15, "Beschreibung": "zum Steuersatz von 0 %", "Kz": 87,
                               "Bemessungsgrundlage (€)": f"{base_87:,}", "Steuer (€)": "—"})
            st.dataframe(form_a, use_container_width=True, hide_index=True)

        # Section B: Steuerfreie Umsätze
        base_41 = kz_base_rounded.get("41", 0)
        if base_41:
            st.markdown("**B. Steuerfreie Lieferungen und sonstige Leistungen**")
            form_b = [{"Zeile": 19, "Beschreibung": "Innergemeinschaftliche Lieferungen (§4 Nr.1b)", "Kz": 41,
                        "Bemessungsgrundlage (€)": f"{base_41:,}"}]
            st.dataframe(form_b, use_container_width=True, hide_index=True)

        # Section C: Innergemeinschaftliche Erwerbe
        base_89 = kz_base_rounded.get("89", 0)
        val_61 = kz_input_tax_sums.get("61", 0.0)
        if base_89:
            st.markdown("**C. Innergemeinschaftliche Erwerbe**")
            form_c = [{"Zeile": 25, "Beschreibung": "zum Steuersatz von 19 %", "Kz": 89,
                        "Bemessungsgrundlage (€)": f"{base_89:,}", "Steuer (€)": f"{base_89 * 0.19:.2f}"}]
            st.dataframe(form_c, use_container_width=True, hide_index=True)

        # Section F: Abziehbare Vorsteuerbeträge
        val_66 = kz_input_tax_sums.get("66", 0.0)
        val_67 = kz_input_tax_sums.get("67", 0.0)
        if val_66 or val_61 or val_67:
            st.markdown("**F. Abziehbare Vorsteuerbeträge**")
            form_f = []
            if val_66:
                form_f.append({"Zeile": 38, "Beschreibung": "Vorsteuerbeträge aus Rechnungen", "Kz": 66,
                               "Betrag (€)": f"{val_66:.2f}"})
            if val_61:
                form_f.append({"Zeile": 39, "Beschreibung": "Vorsteuer aus innergemeinschaftlichem Erwerb", "Kz": 61,
                               "Betrag (€)": f"{val_61:.2f}"})
            if val_67:
                form_f.append({"Zeile": 41, "Beschreibung": "Vorsteuer aus §13b Leistungen", "Kz": 67,
                               "Betrag (€)": f"{val_67:.2f}"})
            st.dataframe(form_f, use_container_width=True, hide_index=True)

        # Section H: Vorauszahlung
        st.markdown("**H. Vorauszahlung/Überschuss**")
        form_h = [{"Zeile": 50, "Beschreibung": "Verbleibende USt-Vorauszahlung (Kz 83)", "Kz": 83,
                    "Betrag (€)": f"{zahllast:.2f}"}]
        st.dataframe(form_h, use_container_width=True, hide_index=True)

        if zahllast > 0:
            st.info(f"Zahllast: {zahllast:.2f} € an das Finanzamt zu überweisen.")
        elif zahllast < 0:
            st.success(f"Erstattung: {abs(zahllast):.2f} € vom Finanzamt.")
        else:
            st.caption("Keine Zahllast.")

    st.download_button("📥 Download UStVA XML (ELSTER)", ustva_xml, f"ustva_{sel_year}_{sel_zeitraum}.xml", "text/xml")

with tab_euer:
    st.header("EÜR (Jährlich)")
    euer_year = st.number_input("Jahr", 2020, 2030, datetime.date.today().year, key="euer_year")
    
    transactions = load_transactions() # Reload to get fresh
    # Need date objects
    parsed_txs = []
    for t in transactions:
        t_new = t.copy()
        if t_new["payment_date"]:
             if isinstance(t_new["payment_date"], str):
                 try:
                     t_new["payment_date"] = datetime.datetime.strptime(t_new["payment_date"], "%Y-%m-%d").date()
                 except: pass
        parsed_txs.append(t_new)
        
    euer_xml = generate_euer_xml(parsed_txs, euer_year)
    
    # Dashboard
    relevant = [t for t in parsed_txs if t.get("payment_date") and isinstance(t["payment_date"], (datetime.date, datetime.datetime)) and t["payment_date"].year == euer_year]
    
    total_inc = sum(t["net_amount"] for t in relevant if t["type"] == "Einnahme")
    total_exp = sum(t["net_amount"] for t in relevant if t["type"] == "Ausgabe")
    profit = total_inc - total_exp
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Betriebseinnahmen", f"{total_inc:.2f} €")
    k2.metric("Betriebsausgaben", f"{total_exp:.2f} €")
    k3.metric("Gewinn", f"{profit:.2f} €", delta=f"{profit:.2f} €")
    
    st.subheader("Ausgaben nach Kategorie")
    # Group by category
    cats = {}
    for t in relevant:
        if t["type"] == "Ausgabe":
            c = t.get("category", "Unkategorisiert")
            cats[c] = cats.get(c, 0.0) + t["net_amount"]
            
    if cats:
        st.bar_chart(cats)
    else:
        st.info("Keine Ausgaben in diesem Jahr.")

    st.download_button("Download EÜR XML (ELSTER)", euer_xml, f"euer_{euer_year}.xml", "text/xml")
