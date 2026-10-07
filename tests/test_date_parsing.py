import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "rdc_stamper"))

from stamper_engine import _extract_invoice_date_from_page


class InvoiceDateParsingTests(unittest.TestCase):
    def test_supported_invoice_date_formats(self):
        cases = {
            "Invoice Date: 13th June 2026": date(2026, 6, 13),
            "Invoice Date: 13-jun-26": date(2026, 6, 13),
            "Invoice Date: 13/06-26": date(2026, 6, 13),
            "Invoice Date: Jun 13, 2026": date(2026, 6, 13),
            "Invoice Date: June 13th, 2026": date(2026, 6, 13),
            "Invoice Date: 2026-06-13": date(2026, 6, 13),
            "Date of Invoice\n13.06.2026": date(2026, 6, 13),
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_extract_invoice_date_from_page(text), expected)

    def test_screenshot_text_does_not_take_partial_acknowledgement_date(self):
        text = (
            "Invoice Date : Jun 13, 2026\n"
            "GST Invoice Number : DEMO-INV-5001\n"
            "Ackno.Date : 2026-07-01 17:20:00"
        )

        self.assertEqual(_extract_invoice_date_from_page(text), date(2026, 6, 13))

    def test_unreadable_invoice_date_does_not_borrow_acknowledgement_date(self):
        text = (
            "Invoice Date : unreadable\n"
            "Ackno.Date : 2026-07-01 17:20:00"
        )

        self.assertIsNone(_extract_invoice_date_from_page(text))

    def test_full_iso_fallback_is_not_parsed_from_the_middle(self):
        self.assertEqual(
            _extract_invoice_date_from_page("Ackno.Date : 2026-07-01"),
            date(2026, 7, 1),
        )


if __name__ == "__main__":
    unittest.main()
