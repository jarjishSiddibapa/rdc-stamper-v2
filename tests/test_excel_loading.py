import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "rdc_stamper"))

from stamper_engine import StamperEngine, build_targets_from_df


def write_workbook(directory, rows, columns):
    path = Path(directory) / "invoice_list.xlsx"
    pd.DataFrame(rows, columns=columns).to_excel(path, index=False)
    return str(path)


class ExcelLoadingRegressionTests(unittest.TestCase):
    def test_numeric_first_column_loads_without_dtype_error(self):
        # A numeric leading column (like an ERP "Co Code") used to break loading
        # under pandas 3.x when the first column was coerced in place.
        with tempfile.TemporaryDirectory() as tmp:
            workbook = write_workbook(
                tmp,
                [[11, "DEMO-INV-1001", "2026-06-03"], [11, "DEMO-INV-1002", "2026-06-04"]],
                ["Co Code ", "Invoice No", "Invoice Date"],
            )
            engine = StamperEngine()
            errors = []
            engine.signals.error.connect(errors.append)

            dataframe = engine.load_excel(workbook)

        self.assertIsNotNone(dataframe)
        self.assertEqual(dataframe.shape, (2, 3))
        self.assertEqual(errors, [])
        self.assertEqual(dataframe.columns[0], "Co Code ")

    def test_targets_are_built_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = write_workbook(
                tmp,
                [
                    ["DEMO-INV-1001", "2026-06-03"],
                    ["DEMO-INV-1001", "2026-06-03"],  # exact duplicate row
                    ["DEMO-INV-1002", "2026-06-04"],
                ],
                ["Invoice No", "Invoice Date"],
            )
            dataframe = StamperEngine().load_excel(workbook)

        targets, total_rows, duplicate_rows = build_targets_from_df(dataframe)

        self.assertEqual(total_rows, 3)
        self.assertEqual(duplicate_rows, 1)
        self.assertEqual(set(targets), {"DEMO-INV-1001", "DEMO-INV-1002"})
        self.assertEqual(targets["DEMO-INV-1001"][0]["date"], date(2026, 6, 3))

    def test_first_column_is_used_when_no_invoice_header_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            workbook = write_workbook(tmp, [["A-1"], ["A-2"]], ["Reference"])
            dataframe = StamperEngine().load_excel(workbook)

        targets, total_rows, _ = build_targets_from_df(dataframe)

        self.assertEqual(total_rows, 2)
        self.assertEqual(set(targets), {"A-1", "A-2"})
        self.assertIsNone(targets["A-1"][0]["date"])


if __name__ == "__main__":
    unittest.main()
