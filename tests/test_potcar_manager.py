import tempfile
import unittest
from pathlib import Path

from app.core.potcar_manager import PotcarManager


class PotcarManagerTests(unittest.TestCase):
    def test_detects_nested_paw_pbe_library(self):
        with tempfile.TemporaryDirectory() as temp:
            configured = Path(temp) / "paw_pbe"
            actual = configured / "paw_pbe" / "Fe"
            actual.mkdir(parents=True)
            (actual / "POTCAR").write_text("Fe potential", encoding="utf-8")
            manager = PotcarManager(configured)
            self.assertEqual(manager.root, configured / "paw_pbe")
            self.assertEqual(manager.find_for_element("Fe"), actual / "POTCAR")


if __name__ == "__main__":
    unittest.main()
