"""Render KSeF FA(3) XML invoice to PDF using fpdf2."""

from __future__ import annotations

from lxml import etree
from fpdf import FPDF

NS = {"fa": "http://crd.gov.pl/wzor/2025/06/25/13775/"}


def _t(el: etree._Element | None, default: str = "") -> str:
    """Extract text from element or return default."""
    return el.text.strip() if el is not None and el.text else default


def _find(root: etree._Element, xpath: str) -> etree._Element | None:
    return root.find(xpath, NS)


def _findall(root: etree._Element, xpath: str) -> list[etree._Element]:
    return root.findall(xpath, NS)


def render_invoice_pdf(xml_bytes: bytes) -> bytes:
    """Parse FA(3) XML and render a simple PDF representation."""
    root = etree.fromstring(xml_bytes)

    # Extract header
    invoice_number = _t(_find(root, ".//fa:Fa/fa:P_2"))
    issue_date = _t(_find(root, ".//fa:Fa/fa:P_1"))
    sell_date = _t(_find(root, ".//fa:Fa/fa:P_6"))
    currency = _t(_find(root, ".//fa:Fa/fa:KodWaluty"), "PLN")

    # Seller (Podmiot1)
    seller_name = _t(_find(root, ".//fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:Nazwa"))
    seller_nip = _t(_find(root, ".//fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:NIP"))
    seller_addr = _t(_find(root, ".//fa:Podmiot1/fa:Adres/fa:AdresL1"))

    # Buyer (Podmiot2)
    buyer_name = _t(_find(root, ".//fa:Podmiot2/fa:DaneIdentyfikacyjne/fa:Nazwa"))
    buyer_nip = _t(_find(root, ".//fa:Podmiot2/fa:DaneIdentyfikacyjne/fa:NIP"))
    buyer_addr = _t(_find(root, ".//fa:Podmiot2/fa:Adres/fa:AdresL1"))

    # Totals
    net_total = _t(_find(root, ".//fa:Fa/fa:P_13_1"))
    vat_total = _t(_find(root, ".//fa:Fa/fa:P_14_1"))
    gross_total = _t(_find(root, ".//fa:Fa/fa:P_15"))

    # Line items
    lines = _findall(root, ".//fa:Fa/fa:FaWiersz")

    # Build PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Try to find a Unicode TTF font for Polish characters
    _use_unicode = False
    import os
    import logging
    logging.getLogger("fpdf").setLevel(logging.ERROR)

    _font_candidates = [
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Geneva.ttf",
    ]
    for font_path in _font_candidates:
        if os.path.exists(font_path):
            try:
                pdf.add_font("UniFont", "", font_path, uni=True)
                _use_unicode = True
                break
            except Exception:
                continue

    def _set_font(style: str = "", size: int = 10) -> None:
        if _use_unicode:
            pdf.set_font("UniFont", "", size)
        else:
            pdf.set_font("Helvetica", style, size)

    # Title
    _set_font("B", 14)
    pdf.cell(0, 10, f"Faktura VAT {invoice_number}", new_x="LMARGIN", new_y="NEXT")

    _set_font("", 9)
    pdf.cell(0, 5, f"Data wystawienia: {issue_date}    Data sprzedazy: {sell_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Seller / Buyer
    col_w = 90
    y_start = pdf.get_y()

    _set_font("B", 10)
    pdf.cell(col_w, 6, "Sprzedawca", new_x="RIGHT")
    pdf.cell(col_w, 6, "Nabywca", new_x="LMARGIN", new_y="NEXT")

    _set_font("", 9)
    pdf.cell(col_w, 5, seller_name, new_x="RIGHT")
    pdf.cell(col_w, 5, buyer_name, new_x="LMARGIN", new_y="NEXT")

    pdf.cell(col_w, 5, f"NIP: {seller_nip}", new_x="RIGHT")
    pdf.cell(col_w, 5, f"NIP: {buyer_nip}", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(col_w, 5, seller_addr, new_x="RIGHT")
    pdf.cell(col_w, 5, buyer_addr, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # Line items table
    _set_font("B", 8)
    headers = ["Lp", "Nazwa", "J.m.", "Ilosc", "Cena netto", "VAT%", "Wartosc netto", "Kwota VAT"]
    widths = [8, 60, 12, 15, 22, 12, 25, 25]

    pdf.set_fill_color(230, 230, 230)
    for h, w in zip(headers, widths):
        pdf.cell(w, 6, h, border=1, fill=True)
    pdf.ln()

    _set_font("", 8)
    for row in lines:
        nr = _t(row.find("fa:NrWierszaFa", NS))
        name = _t(row.find("fa:P_7", NS))
        unit = _t(row.find("fa:P_8A", NS))
        qty = _t(row.find("fa:P_8B", NS))
        net_price = _t(row.find("fa:P_11", NS))
        vat_rate = _t(row.find("fa:P_12", NS))
        # Net value = qty * net_price (per unit)
        try:
            net_val = f"{float(qty) * float(net_price):.2f}" if qty and net_price else ""
        except ValueError:
            net_val = ""
        vat_amount = _t(row.find("fa:P_11Vat", NS))

        # Truncate long names
        if len(name) > 30:
            name = name[:28] + ".."

        vals = [nr, name, unit, qty, net_price, vat_rate, net_val, vat_amount]
        for v, w in zip(vals, widths):
            pdf.cell(w, 5, v, border=1)
        pdf.ln()

    pdf.ln(5)

    # Totals
    _set_font("B", 10)
    pdf.cell(0, 6, f"Razem:  netto {net_total} {currency}  |  VAT {vat_total} {currency}  |  brutto {gross_total} {currency}",
             new_x="LMARGIN", new_y="NEXT")

    # Payment info
    payment_term = _t(_find(root, ".//fa:Fa/fa:Platnosc/fa:TerminPlatnosci/fa:Termin"))
    bank_account = _t(_find(root, ".//fa:Fa/fa:Platnosc/fa:RachunekBankowy/fa:NrRB"))
    bank_name = _t(_find(root, ".//fa:Fa/fa:Platnosc/fa:RachunekBankowy/fa:NazwaBanku"))

    if payment_term or bank_account:
        pdf.ln(5)
        _set_font("B", 9)
        pdf.cell(0, 5, "Platnosc:", new_x="LMARGIN", new_y="NEXT")
        _set_font("", 9)
        if payment_term:
            pdf.cell(0, 5, f"Termin platnosci: {payment_term}", new_x="LMARGIN", new_y="NEXT")
        if bank_account:
            pdf.cell(0, 5, f"Rachunek: {bank_account} ({bank_name})", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
