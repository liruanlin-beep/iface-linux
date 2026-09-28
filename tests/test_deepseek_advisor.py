import tempfile
import unittest
from pathlib import Path

from app.core.deepseek_advisor import (
    IncarSuggestion,
    _url_opener,
    apply_incar_suggestions,
    parse_incar,
    validate_suggestions,
)


class DeepSeekAdvisorTests(unittest.TestCase):
    def test_protected_and_unknown_parameters_are_rejected(self):
        changes, warnings = validate_suggestions(
            [
                {"key": "NELM", "new_value": "180", "reason": "SCF", "confidence": 0.8},
                {"key": "LDAUU", "new_value": "5 0", "reason": "unsafe"},
                {"key": "SYSTEM", "new_value": "x", "reason": "not allowed"},
                {"key": "ENCUT", "new_value": "rm -rf", "reason": "invalid"},
            ],
            {"NELM": "60"},
        )
        self.assertEqual([(item.key, item.new_value) for item in changes], [("NELM", "180")])
        self.assertEqual(len(warnings), 3)

    def test_apply_creates_backup_and_preserves_comment(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "INCAR"
            path.write_text("ENCUT = 400 # original\nISMEAR = 1\n", encoding="utf-8")
            backup = apply_incar_suggestions(
                path,
                [
                    IncarSuggestion("ENCUT", "400", "520", "accuracy", 0.9),
                    IncarSuggestion("NELM", "", "160", "SCF", 0.8),
                ],
            )
            self.assertTrue(backup.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("ENCUT = 520 # original", text)
            self.assertIn("NELM = 160", text)
            self.assertEqual(parse_incar(path)["ENCUT"], "520")

    def test_proxy_format_is_validated(self):
        self.assertIsNotNone(_url_opener("http://127.0.0.1:7892"))
        with self.assertRaises(ValueError):
            _url_opener("127.0.0.1")


if __name__ == "__main__":
    unittest.main()
