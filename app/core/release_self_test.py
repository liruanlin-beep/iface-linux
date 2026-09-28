"""Offline acceptance for both source and frozen releases; no SSH or VASP calls."""

import json
import os
from pathlib import Path
import tempfile
import traceback


def run_release_self_test(report_path):
    from app.version import VERSION

    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"version": VERSION, "passed": False, "checks": [], "scope": "offline; synthetic data; no cluster"}
    previous = os.environ.get("IFACE_DATA_DIR")
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="iface-release-") as directory:
            os.environ["IFACE_DATA_DIR"] = directory
            # Import after selecting the isolated data root.
            from app.core.config_manager import ConfigManager
            from app.core.paths import USER_DATA_DIR
            from app.core.structure_model import load_structure, to_pymatgen_structure
            from app.core.input_generators import write_poscar, write_incar, write_kpoints
            from app.core.high_throughput_self_test import run_high_throughput_self_test
            from app.core.science_exports import PdosDataset, export_pdos_publication
            import numpy as np
            import paramiko
            import tkinterdnd2
            from pymatgen.analysis.interfaces.coherent_interfaces import CoherentInterfaceBuilder
            from app.ui.main_window import MainWindow

            root = Path(directory)
            if USER_DATA_DIR != root.resolve():
                raise RuntimeError("Data isolation failed: paths were already imported")
            config = ConfigManager()
            if config.data["potcar_root"] or config.data["default_remote_host"]:
                raise RuntimeError("Fresh configuration contains machine-specific defaults")
            report["checks"].append("isolated fresh configuration")
            structure_path = root / "POSCAR"
            structure_path.write_text("Al demo\n1.0\n4.05 0 0\n0 4.05 0\n0 0 4.05\nAl\n4\nDirect\n0 0 0\n0 0.5 0.5\n0.5 0 0.5\n0.5 0.5 0\n", encoding="utf-8")
            structure = load_structure(structure_path)
            assert len(to_pymatgen_structure(structure)) == 4
            cif = root / "Al.cif"
            to_pymatgen_structure(structure).to(filename=str(cif))
            assert len(load_structure(cif).atoms) == 4
            structure.make_supercell(2, 1, 1)
            write_poscar(root / "POSCAR-expanded", structure)
            assert len(load_structure(root / "POSCAR-expanded").atoms) == 8
            write_incar(root / "INCAR")
            write_kpoints(root / "KPOINTS")
            report["checks"].append("POSCAR/CIF import, supercell and input export")
            exports = export_pdos_publication(PdosDataset(
                energies_ev=np.array([-1., 0., 1.]), fermi_ev=0.,
                channels={"Demo": {"up": np.array([.2, 1., .3]), "down": np.array([.1, .4, .2])}},
                source="synthetic acceptance data"), root / "figures", stem="demo")
            assert all(Path(path).stat().st_size > 0 for path in exports.values())
            report["checks"].append("PNG/TIFF/PDF/SVG/XLSX export")
            report["queue"] = run_high_throughput_self_test().to_dict()
            assert report["queue"]["passed"]
            report["checks"].append("48-workflow queue, deduplication and crash recovery")
            app = MainWindow()
            app.withdraw()
            ui_errors = []
            app.report_callback_exception = lambda *exc: ui_errors.append(''.join(traceback.format_exception(*exc)))
            app.viewer.set_structure(structure)
            app.update_idletasks()
            app.update()
            assert VERSION in app.title()
            assert not ui_errors, ui_errors
            assert hasattr(app, "drop_target_register")
            app.destroy()
            app = None
            report["checks"].append("Tk main window, structure viewer, drag/drop and callbacks")
            report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:
                pass
        if previous is None:
            os.environ.pop("IFACE_DATA_DIR", None)
        else:
            os.environ["IFACE_DATA_DIR"] = previous
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
