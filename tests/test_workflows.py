import contextlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from iface import api
from iface.cli import main, menu
from iface.files import archive_outputs, fingerprint
from iface.formats import Poscar
from iface.neb import minimum_image
from iface.scheduler import submit


POSCAR = "Al test\n1\n4 0 0\n0 4 0\n0 0 4\nAl\n1\nDirect\n0.9 0 0\n"
# Deliberately synthetic metadata only. This is NOT a usable VASP potential.
POTCAR = "TITEL = PAW_PBE Al TEST\nVRHFIN =Al: test\nENMAX = 240.0;\nEnd of Dataset\n"


class Workflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.poscar = self.root / "POSCAR"
        self.poscar.write_text(POSCAR)
        self.library = self.root / "potentials"
        (self.library / "Al").mkdir(parents=True)
        (self.library / "Al" / "POTCAR").write_text(POTCAR)

    def prepared(self, name="run", preset="static", scheduler="slurm"):
        target = self.root / name
        api.prepare(self.poscar, target, preset=preset, potcar_root=self.library, scheduler=scheduler)
        return target

    def outcar(self, directory, energy=-4, finished=True, frequencies=()):
        text = f" free  energy   TOTEN  = {energy} eV\n"
        text += " POSITION                                       TOTAL-FORCE (eV/Angst)\n ---\n 0 0 0 0.03 0.04 0\n ---\n"
        for i, (value, imaginary) in enumerate(frequencies, 1):
            text += f" {i} {'f/i' if imaginary else 'f'} = {value} THz\n"
        if finished:
            text += " General timing and accounting informations for this job:\n"
        (directory / "OUTCAR").write_text(text)

    def test_prepare_complete_and_preflight(self):
        target = self.prepared()
        self.assertTrue(api.preflight(target)["ok"])
        self.assertEqual(api.read_incar(target / "INCAR")["NSW"], "0")
        self.assertEqual(Poscar.read(target / "POSCAR").atom_count, 1)
        self.assertNotIn(b"\r", (target / "job.sh").read_bytes())

    def test_prepare_without_potential_is_not_submittable(self):
        target = self.root / "incomplete"
        api.prepare(self.poscar, target)
        self.assertFalse(api.preflight(target)["ok"])

    def test_existing_directory_is_not_overwritten(self):
        target = self.prepared()
        before = fingerprint(target)
        with self.assertRaises(FileExistsError):
            api.prepare(self.poscar, target)
        self.assertEqual(before, fingerprint(target))

    def test_failed_bundle_not_published(self):
        source = self.prepared()
        (source / "POTCAR").unlink()
        (source / "CONTCAR").write_text(POSCAR)
        target = self.root / "static"
        with self.assertRaises(FileNotFoundError):
            api.to_static(source, target)
        self.assertFalse(target.exists())

    def test_static_preserves_physics_and_uses_contcar(self):
        source = self.prepared(preset="relax")
        (source / "INCAR").write_text("ENCUT=600; ISPIN=2; MAGMOM=1\nGGA=PE\nNSW=200\n")
        (source / "CONTCAR").write_text(POSCAR.replace("0.9 0 0", "0.2 0 0"))
        target = self.root / "static"
        api.to_static(source, target)
        params = api.read_incar(target / "INCAR")
        self.assertEqual(params["GGA"], "PE")
        self.assertEqual(params["MAGMOM"], "1")
        self.assertAlmostEqual(Poscar.read(target / "POSCAR").fractional[0, 0], 0.2)

    def test_exact_potential_variant_no_fallback(self):
        (self.library / "Al").rename(self.library / "Al_pv")
        with self.assertRaises(FileNotFoundError):
            api.potcar_bytes(Poscar.read(self.poscar), self.library)
        expected = (self.library / "Al_pv" / "POTCAR").read_bytes().rstrip() + b"\n"
        self.assertEqual(api.potcar_bytes(Poscar.read(self.poscar), self.library, ["Al_pv"]), expected)

    def test_potential_element_mismatch_rejected(self):
        target = self.prepared()
        (target / "POTCAR").write_text(POTCAR.replace("Al", "Fe"))
        self.assertFalse(api.preflight(target)["ok"])

    def test_poscar_negative_volume_and_cartesian_scale(self):
        self.poscar.write_text(POSCAR.replace("\n1\n4", "\n-125\n4"))
        self.assertAlmostEqual(abs(np.linalg.det(Poscar.read(self.poscar).cell)), 125)
        self.poscar.write_text(POSCAR.replace("\n1\n4", "\n2\n4").replace("Direct", "Cartesian"))
        parsed = Poscar.read(self.poscar)
        self.assertAlmostEqual(parsed.fractional[0, 0], 0.225)
        np.testing.assert_allclose(parsed.cell, np.eye(3) * 8)

    def test_three_scales_and_selective_flags_round_trip(self):
        self.poscar.write_text(POSCAR.replace("\n1\n4", "\n2 3 4\n4").replace("Direct", "Selective dynamics\nCartesian").replace("0.9 0 0", "0.9 0 0 T F T"))
        parsed = Poscar.read(self.poscar)
        self.assertEqual(parsed.flags, [["T", "F", "T"]])
        self.assertAlmostEqual(parsed.fractional[0, 0], 0.225)
        self.poscar.write_text(parsed.text())
        np.testing.assert_allclose(Poscar.read(self.poscar).cell, np.diag([8, 12, 16]))

    def test_invalid_structure_nan_and_count(self):
        for text in (POSCAR.replace("0.9", "nan"), POSCAR.replace("Al\n1\nDirect", "Al\n2\nDirect")):
            self.poscar.write_text(text)
            with self.assertRaises(ValueError):
                Poscar.read(self.poscar)

    def test_invalid_mesh_and_script_injection(self):
        with self.assertRaises(ValueError):
            api.kpoints_text((1, 0, 1))
        with self.assertRaises(ValueError):
            api.script_text(name="job\n#SBATCH --nodes=999")
        with self.assertRaises(ValueError):
            api.script_text(nodes=0)

    def test_pbs_preflight_and_crlf_rejection(self):
        target = self.prepared(scheduler="pbs")
        self.assertTrue(api.preflight(target, "pbs")["ok"])
        script = target / "job.sh"
        script.write_bytes(script.read_bytes().replace(b"\n", b"\r\n"))
        self.assertFalse(api.preflight(target, "pbs")["ok"])

    def test_submit_requires_confirmation(self):
        with patch("iface.scheduler._run") as run:
            with self.assertRaises(ValueError):
                submit(self.prepared())
            run.assert_not_called()

    def test_submit_once_with_durable_record(self):
        target = self.prepared()
        with patch("iface.scheduler.shutil.which", return_value="/usr/bin/sbatch"), patch("iface.scheduler._run", return_value="1234;cluster") as run:
            record = submit(target, confirmed=True)
            self.assertEqual(record["job_id"], "1234")
            with self.assertRaises(ValueError):
                submit(target, confirmed=True)
            self.assertEqual(run.call_count, 1)

    def test_timeout_leaves_unknown_and_blocks_retry(self):
        target = self.prepared()
        with patch("iface.scheduler.shutil.which", return_value="/usr/bin/sbatch"), patch("iface.scheduler._run", side_effect=RuntimeError("timeout")) as run:
            with self.assertRaises(RuntimeError):
                submit(target, confirmed=True)
            self.assertEqual(json.loads((target / ".iface-submission.json").read_text())["state"], "unknown")
            with self.assertRaises(ValueError):
                submit(target, confirmed=True)
            self.assertEqual(run.call_count, 1)

    def test_archive_preview_and_recovery(self):
        target = self.prepared()
        (target / "OUTCAR").write_text("result")
        before = fingerprint(target)
        self.assertFalse(archive_outputs(target)["applied"])
        self.assertTrue((target / "OUTCAR").exists())
        result = archive_outputs(target, apply=True)
        self.assertEqual((Path(result["archive"]) / "OUTCAR").read_text(), "result")
        self.assertEqual(before, fingerprint(target))

    def test_archive_blocked_by_submission_record(self):
        target = self.prepared()
        (target / ".iface-submission.json").write_text('{}')
        with self.assertRaises(ValueError):
            archive_outputs(target, apply=True)

    def test_neb_shortest_path_and_manifest(self):
        source = self.prepared()
        final = self.root / "final"
        final.write_text(POSCAR.replace("0.9 0 0", "0.1 0 0"))
        output = self.root / "neb"
        api.prepare_neb(self.poscar, final, source, output, images=1)
        midpoint = Poscar.read(output / "01" / "POSCAR")
        self.assertAlmostEqual(midpoint.fractional[0, 0], 1.0)
        self.assertTrue(api.preflight(output)["ok"])
        self.assertNotIn("LCLIMB", api.read_incar(output / "INCAR"))

    def test_neb_incompatible_cells_rejected(self):
        source = self.prepared()
        final = self.root / "final"
        final.write_text(POSCAR.replace("4 0 0", "5 0 0"))
        with self.assertRaises(ValueError):
            api.prepare_neb(self.poscar, final, source, self.root / "neb")

    def test_skewed_minimum_image_matches_exhaustive_search(self):
        import itertools
        cell = np.array([[3, 0, 0], [2.7, 0.8, 0], [0.2, 0.2, 4]])
        delta = np.array([[0.49, 0.49, 0.1]])
        exact = minimum_image(delta, cell)
        brute = min(np.linalg.norm((delta[0] - np.array(shift)) @ cell)
                    for shift in itertools.product(range(-4, 5), repeat=3))
        self.assertAlmostEqual(np.linalg.norm(exact[0] @ cell), brute)

    def test_neb_missing_endpoint_energy_is_unknown(self):
        root = self.root / "neb"
        for name in ("00", "01", "02"):
            (root / name).mkdir(parents=True)
        self.outcar(root / "01", energy=-2)
        self.assertIsNone(api.neb_report(root)["forward_barrier_ev"])
        self.outcar(root / "00", energy=-4)
        self.outcar(root / "02", energy=-3)
        report = api.neb_report(root)
        self.assertEqual(report["forward_barrier_ev"], 2)
        self.assertEqual(report["reverse_barrier_ev"], 1)

    def test_vibration_indices_and_vineyard_prefactor(self):
        source = self.prepared()
        output = self.root / "vibration"
        api.prepare_vibration(self.poscar, source, output, [1])
        self.assertEqual(api.read_incar(output / "INCAR")["IBRION"], "5")
        self.outcar(source, frequencies=[(2, False), (3, False), (4, False)])
        self.outcar(output, frequencies=[(2, False), (6, False), (1, True)])
        result = api.effective_frequency(source, output)
        self.assertAlmostEqual(result["effective_frequency_thz"], 2)
        self.outcar(output, frequencies=[(2, True), (6, False), (1, True)])
        with self.assertRaises(ValueError):
            api.effective_frequency(source, output)

    def test_result_force_and_finished_not_converged(self):
        target = self.prepared()
        self.outcar(target)
        report = api.inspect_calculation(target)
        self.assertEqual(report["energy_ev"], -4)
        self.assertAlmostEqual(report["max_force_ev_a"], 0.05)
        self.assertTrue(report["finished"])
        self.assertFalse(report["ionic_converged"])
        self.assertEqual(report["electronic_convergence"], "not_assessed")

    def test_sweep_and_energy_per_atom(self):
        source = self.prepared()
        sweep = self.root / "sweep"
        api.convergence_sweep(source, sweep, "encut", [600, 400])
        self.outcar(sweep / "encut_001", -4)
        self.outcar(sweep / "encut_002", -3.9995)
        report = api.convergence_report(sweep)
        self.assertEqual(report["reference"], 600)
        self.assertAlmostEqual(report["cases"][0]["delta_mev_atom"], 0.5)
        self.assertTrue(report["cases"][0]["within_tolerance"])

    def test_sweep_rejects_relaxation_and_duplicates(self):
        source = self.prepared(preset="relax")
        with self.assertRaises(ValueError):
            api.convergence_sweep(source, self.root / "scan", "encut", [400, 500])
        source = self.prepared(name="static")
        with self.assertRaises(ValueError):
            api.convergence_sweep(source, self.root / "scan", "encut", [400, 400])

    def test_kpoint_sweep(self):
        source = self.prepared()
        target = self.root / "mesh"
        api.convergence_sweep(source, target, "kpoints", [(3, 3, 1), (5, 5, 1)])
        self.assertIn("5 5 1", (target / "kpoints_002" / "KPOINTS").read_text())
        self.assertTrue(api.preflight(target / "kpoints_002")["ok"])

    def test_recursive_results_skip_archives(self):
        target = self.prepared()
        (target / ".iface-archive" / "old").mkdir(parents=True)
        (target / ".iface-archive" / "old" / "POSCAR").write_text(POSCAR)
        rows = api.inspect_tree(target, recursive=True)
        self.assertEqual(len(rows), 1)

    def test_cli_round_trip_and_english_errors(self):
        target = self.root / "path with spaces"
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["os", "prepare", str(self.poscar), str(target), "--potcar-root", str(self.library)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())["kind"], "relax")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["os", "check", str(self.root / "missing")]), 2)

    def test_menu_navigation(self):
        with patch("builtins.input", side_effect=["1", "4", str(self.root / "KPOINTS"), "--mesh 4x4x1", "0"]), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(menu(), 0)
        self.assertIn("Optimization and static", output.getvalue())
        self.assertIn("4 4 1", (self.root / "KPOINTS").read_text())

    def test_import_without_desktop(self):
        result = subprocess.run([sys.executable, "-c", "import iface.api,sys; assert 'tkinter' not in sys.modules; print('headless OK')"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("headless OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
