import os
import sys
import tempfile
import unittest
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "rdc_stamper"))

from stamper_engine import StamperEngine


class InstalledRuntimeRegressionTests(unittest.TestCase):
    def test_pdf_merge_uses_user_temp_directory(self):
        with tempfile.TemporaryDirectory() as input_dir:
            input_paths = []
            for index in range(2):
                input_path = Path(input_dir) / f"input-{index}.pdf"
                document = fitz.open()
                document.new_page()
                document.save(input_path)
                document.close()
                input_paths.append(str(input_path))

            output_path = Path(StamperEngine().merge_pdfs(input_paths))
            try:
                self.assertEqual(
                    output_path.parent,
                    Path(tempfile.gettempdir()) / "RDC_Stamper_V2",
                )
                self.assertNotEqual(output_path.parent, PROJECT_ROOT)
                with fitz.open(output_path) as merged:
                    self.assertEqual(merged.page_count, 2)
            finally:
                if output_path.exists():
                    os.remove(output_path)


if __name__ == "__main__":
    unittest.main()
