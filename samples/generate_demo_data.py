"""Generate fictional demo inputs for RDC Stamper V2.

Creates two files next to this script:

* demo_invoices.pdf       - an 8-page "scanned bundle" of made-up tax invoices,
                            including a duplicate page, a blank page and one
                            invoice whose printed date differs from the list.
* demo_invoice_list.xlsx  - the matching invoice list, including one invoice
                            that is not in the PDF and one date mismatch.

Run:  python samples/generate_demo_data.py
"""
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

OUT = Path(__file__).resolve().parent

# invoice number, printed date, customer, amount
INVOICES = [
    ("DEMO-INV-1001", date(2026, 6, 3), "Northwind Builders Pvt Ltd", 48250.00),
    ("DEMO-INV-1002", date(2026, 6, 4), "Lakeside Infra Ltd", 126400.50),
    ("DEMO-INV-1003", date(2026, 6, 4), "Harbor Constructions", 73980.00),
    ("DEMO-INV-1004", date(2026, 6, 9), "Summit Developers", 215600.75),
    ("DEMO-INV-1005", date(2026, 6, 11), "Orchid Realty LLP", 39120.00),
]

# What the Excel list claims. 1004 has a different date (mismatch), 1099 is not in the PDF.
LIST_ROWS = [
    ("DEMO-INV-1001", date(2026, 6, 3)),
    ("DEMO-INV-1002", date(2026, 6, 4)),
    ("DEMO-INV-1003", date(2026, 6, 4)),
    ("DEMO-INV-1004", date(2026, 6, 10)),
    ("DEMO-INV-1005", date(2026, 6, 11)),
    ("DEMO-INV-1099", date(2026, 6, 12)),
]


def draw_invoice(page, number, inv_date, customer, amount):
    page.insert_text((50, 70), "TAX INVOICE", fontsize=22, fontname="helv")
    page.insert_text((50, 100), "Demo Materials Pvt Ltd  |  Fictional sample document", fontsize=10)
    page.draw_line((50, 112), (545, 112))
    page.insert_text((50, 145), f"Invoice No: {number}", fontsize=13)
    page.insert_text((330, 145), f"Invoice Date: {inv_date.strftime('%d-%b-%Y')}", fontsize=13)
    page.insert_text((50, 180), f"Billed to: {customer}", fontsize=12)
    y = 230
    for item, qty, rate in [("Ready-mix concrete M25", 20, amount / 25), ("Transport", 1, amount * 0.2)]:
        page.insert_text((50, y), item, fontsize=11)
        page.insert_text((330, y), f"{qty}", fontsize=11)
        page.insert_text((420, y), f"{rate:,.2f}", fontsize=11)
        y += 24
    page.draw_line((50, y), (545, y))
    page.insert_text((330, y + 28), f"Total: INR {amount:,.2f}", fontsize=13)
    page.insert_text((50, 760), "This is a computer-generated demo invoice.", fontsize=8)


def main():
    doc = fitz.open()
    for number, inv_date, customer, amount in INVOICES:
        draw_invoice(doc.new_page(), number, inv_date, customer, amount)
    # a duplicate page for invoice 1002 and a blank page, to show the duplicate / blank handling
    draw_invoice(doc.new_page(), *INVOICES[1])
    doc.new_page()
    doc.save(OUT / "demo_invoices.pdf")
    doc.close()

    pd.DataFrame(LIST_ROWS, columns=["Invoice No", "Invoice Date"]).to_excel(
        OUT / "demo_invoice_list.xlsx", index=False
    )
    print("Wrote demo_invoices.pdf and demo_invoice_list.xlsx in", OUT)


if __name__ == "__main__":
    main()
