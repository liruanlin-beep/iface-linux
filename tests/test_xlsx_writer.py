import tempfile
import unittest
import zipfile
from pathlib import Path

from app.core.xlsx_writer import write_xlsx


class XlsxWriterTests(unittest.TestCase):
    def test_writes_valid_xlsx_container(self):
        with tempfile.TemporaryDirectory() as temp:
            path = write_xlsx(
                Path(temp) / "data.xlsx",
                [("Data", [["x", "y"], [1, 2.5], [2, "text"]])],
            )
            with zipfile.ZipFile(path) as archive:
                self.assertIn("xl/workbook.xml", archive.namelist())
                sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn("text", sheet)
                self.assertIn("2.5", sheet)


if __name__ == "__main__":
    unittest.main()
