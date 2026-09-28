import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.core.science_exports import PdosDataset, export_pdos_publication


class ScienceExportTests(unittest.TestCase):
    def test_pdos_exports_pdf_svg_raster_and_excel(self):
        dataset = PdosDataset(
            energies_ev=np.asarray([-1.0, 0.0, 1.0]),
            fermi_ev=5.25,
            channels={
                "Total DOS": {
                    "up": np.asarray([0.2, 1.0, 0.3]),
                    "down": np.asarray([0.1, 0.4, 0.2]),
                }
            },
            source="synthetic",
        )
        with tempfile.TemporaryDirectory() as temp:
            exported = export_pdos_publication(
                dataset,
                Path(temp),
                stem="PDOS_smoke",
            )
            self.assertEqual(
                {"png", "tiff", "pdf", "svg", "excel"},
                set(exported),
            )
            for path in exported.values():
                self.assertTrue(Path(path).is_file())
                self.assertGreater(Path(path).stat().st_size, 0)
