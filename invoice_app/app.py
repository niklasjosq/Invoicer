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
    ts.append(t)
    save_transactions(ts)

# Default values
DEFAULT_ITEM = {"name": "Consulting Services", "qty": 1.0, "price": 100.0, "vat_percent": 19.0}

if "xml_content" not in st.session_state:
    st.session_state.xml_content = None
if "zugferd_pdf" not in st.session_state:
    st.session_state.zugferd_pdf = None
if "line_items_list" not in st.session_state:
    st.session_state.line_items_list = [DEFAULT_ITEM.copy()]

tab_input, tab_xml, tab_pdf, tab_scanner, tab_ustva, tab_euer = st.tabs(["📝 Input Data", "📄 XML Preview", "👁️ PDF Preview", "📂 Scanner", "📈 UStVA (Monatlich)", "📊 EÜR (Jährlich)"])

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
        st.code(st.session_state.xml_content, language="xml")
        st.download_button("Download XML", st.session_state.xml_content, "factur-x.xml", "text/xml")

with tab_pdf:
    st.header("PDF Preview")
    if st.session_state.zugferd_pdf:
        pdf_viewer(st.session_state.zugferd_pdf, width=800)
        st.download_button("Download ZUGFeRD PDF", st.session_state.zugferd_pdf, f"{inv_id}.pdf", "application/pdf")

with tab_scanner:
    st.header("Invoice Scanner")
    
    # Directory input
    default_dir = os.getenv("INVOICE_DIRECTORY", ".")
    invoice_dir = st.text_input("Invoice Directory", value=default_dir)
    
    if st.button("Scan Directory"):
        if not os.path.exists(invoice_dir):
            st.error("Directory not found!")
        else:
            found_files = []
            for root, dirs, files in os.walk(invoice_dir):
                for file in files:
                    if file.lower().endswith((".pdf", ".xml")):
                         found_files.append(os.path.join(root, file))
            
            st.info(f"Found {len(found_files)} potential invoice files.")
            
            new_txs = []
            current_txs = load_transactions()
            current_ids = [t["id"] for t in current_txs]
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, fpath in enumerate(found_files):
                status_text.text(f"Processing {os.path.basename(fpath)}...")
                data = None
                
                # Simple Logic: Process both, ID check prevents duplicates
                if fpath.lower().endswith(".pdf"):
                    data = extract_data_from_pdf(fpath)
                elif fpath.lower().endswith(".xml"):
                    data = extract_data_from_xml_file(fpath)
                
                if data:
                    # Check if already exists
                    if data["id"] and data["id"] not in current_ids:
                        new_txs.append(data)
                        current_ids.append(data["id"])
                
                progress_bar.progress((i + 1) / len(found_files))
            
            status_text.text("Scan complete!")
            
            if new_txs:
                st.success(f"Successfully imported {len(new_txs)} new invoices!")
                current_txs.extend(new_txs)
                save_transactions(current_txs)
                st.dataframe(new_txs)
            else:
                st.warning("No new invoices found or extracted.")

with tab_ustva:
    st.header("UStVA (Monatlich)")
    
    col_u1, col_u2 = st.columns(2)
    sel_year = col_u1.number_input("Jahr", 2020, 2030, datetime.date.today().year, key="ustva_year")
    sel_month = col_u2.selectbox("Monat", range(1, 13), index=datetime.date.today().month-1, key="ustva_month")

    st.markdown("### Steuerfall (Unternehmer)")
    sender_default_name = ""
    sender_name_area = st.session_state.get("sender_name_area", "")
    if sender_name_area:
        sender_default_name = sender_name_area.split("\n")[0].strip()
    if "ustva_name" not in st.session_state and sender_default_name:
        st.session_state.ustva_name = sender_default_name
    col_tax_1, col_tax_2, col_tax_3 = st.columns(3)
    ustva_stnr = col_tax_1.text_input(
        "Steuernummer (StNr)",
        key="ustva_stnr",
        help="Wird im XML als <Unternehmer><StNr>...</StNr> gesetzt.",
    )
    ustva_name = col_tax_2.text_input("Nachname/Firmenname", key="ustva_name")
    ustva_vorname = col_tax_3.text_input("Vorname", key="ustva_vorname")
    
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
    
    # Separate data editors for Einnahmen (Ausgangsrechnungen) and Ausgaben (Eingangsrechnungen)
    st.subheader("📤 Ausgangsrechnungen (Einnahmen)")
    # Filter strictly by Type
    ausgangs_txs = [t for t in transactions if t.get("type") == "Einnahme"]
    
    ausgaben_col_config = {
        "id": st.column_config.TextColumn("Rechnungs-Nr.", disabled=True),
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
            options=get_category_options("Einnahme"),
            help="Wähle die passende Kategorie",
            required=True
        )
    }
    edited_ausgangs = st.data_editor(
        ausgangs_txs,
        key="ausgangs_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config=ausgaben_col_config
    )
    
    st.subheader("📥 Eingangsrechnungen (Ausgaben)")
    eingangs_txs = [t for t in transactions if t.get("type") == "Ausgabe"]
    
    eingangs_col_config = {
        "id": st.column_config.TextColumn("Rechnungs-Nr.", disabled=True),
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
            options=get_category_options("Ausgabe"),
            help="Wähle die passende Kategorie",
            required=True
        )
    }
    edited_eingangs = st.data_editor(
        eingangs_txs,
        key="eingangs_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config=eingangs_col_config
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
        sel_month,
        sel_year,
        stnr=ustva_stnr,
        name=ustva_name,
        vorname=ustva_vorname,
    )
    
    # Calculate UStVA metrics matching ELSTER logic
    totals = calculate_ustva_totals(edited_txs, sel_month, sel_year)
    count_relevant = totals["count_relevant"]
    kz_base_sums = totals["kz_base_sums"]
    kz_input_tax_sums = totals["kz_input_tax_sums"]
    sum_sales_vat = totals["sum_sales_vat"]
    sum_input_tax = totals["sum_input_tax"]
    zahllast = totals["zahllast"]
    
    st.caption(f"Berechnungsgrundlage: {count_relevant} Buchungen im Zeitraum {sel_month:02d}/{sel_year}.")
    # Debug info (can be removed later)
    if count_relevant > 0 and sum_sales_vat == 0 and sum_input_tax == 0:
        st.warning("Keine Steuer berechnet. Prüfe Kategorien:")
        st.write("Erkannte Basis-Summen (KZ):", kz_base_sums)
        st.write("Erkannte Vorsteuer-Summen (KZ):", kz_input_tax_sums)
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Umsatzsteuer (Einnahmen)", f"{sum_sales_vat:.2f} €")
    m2.metric("Vorsteuer (Ausgaben)", f"{sum_input_tax:.2f} €")
    m3.metric("Zahllast", f"{zahllast:.2f} €", delta_color="inverse")
    
    st.download_button("Download UStVA XML (ELSTER)", ustva_xml, f"ustva_{sel_year}_{sel_month:02d}.xml", "text/xml")

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
