#!/usr/bin/env python3
"""Reproduce 22 revised independent checks against an installed iface package.

This public runner is an infrastructure adaptation, not an original execution log.
Fixtures are synthetic. Scheduler calls are mocked. No VASP executable or licensed
POTCAR dataset is needed; the short POTCAR TEST metadata is generated at runtime.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import importlib.metadata
import itertools
import json
import math
import platform
from pathlib import Path
import re
import sys
import sysconfig
import traceback
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True,
                    help='New directory for reports and synthetic fixtures; must not already exist.')
args = parser.parse_args()
if platform.system() != 'Linux':
    parser.error('Run this installed-package validation with a Linux interpreter.')
if not __debug__:
    parser.error('Assertions are required; do not use Python -O or PYTHONOPTIMIZE.')
if sys.prefix == sys.base_prefix:
    parser.error('Use a virtual-environment interpreter with iface installed.')

# Deliberately do not insert any source directory into sys.path.
import numpy as np
import iface
from iface import api
from iface.formats import Poscar
from iface.neb import minimum_image, neb_report, effective_frequency
from iface.results import inspect_calculation
from iface.scheduler import submit

installed_roots = sorted({Path(sysconfig.get_path(key)).resolve() for key in ('purelib', 'platlib')})
imported_api_path = Path(api.__file__).resolve()
if not any(imported_api_path.is_relative_to(root) and root.name == 'site-packages' for root in installed_roots):
    raise RuntimeError(f'iface must import from this interpreter site-packages; observed {imported_api_path}')
distribution = importlib.metadata.distribution('iface-linux')
distribution_api_path = Path(distribution.locate_file('iface/api.py')).resolve()
if distribution_api_path != imported_api_path:
    raise RuntimeError('Imported iface.api does not match the installed distribution file.')
if iface.__version__ != distribution.version:
    raise RuntimeError('Imported package version and installed distribution version disagree.')
for module_name, module in tuple(sys.modules.items()):
    if (module_name == 'iface' or module_name.startswith('iface.')) and getattr(module, '__file__', None):
        module_path = Path(module.__file__).resolve()
        if not any(module_path.is_relative_to(root) for root in installed_roots):
            raise RuntimeError(f'An iface module came from outside the installed environment: {module_path}')

ORIGIN_SCRIPT_SHA256 = '7433df7a80b1692e04b27d960d4cd5d2f84089286512dd8300b4e0e090af709a'
LINUX_ADAPTATION_SCRIPT_SHA256 = 'f2a5b4cce2525fc5e4ba67dff9032ca654932fc85b651af6c2571d8dd435be36'
SCIENTIFIC_BLOCK_SHA256 = '9f8ba27db2c78b49253c012270c444dbf20a9edf44aa14bd7f725b5c9392ce3a'
script_path = Path(__file__).resolve()
script_text = script_path.read_text(encoding='utf-8')
actual_scientific = script_text.split('# BEGIN UNCHANGED SCIENTIFIC PROTOCOL\n', 1)[1].split('# END UNCHANGED SCIENTIFIC PROTOCOL\n', 1)[0]
actual_scientific_hash = hashlib.sha256(actual_scientific.encode()).hexdigest()
if actual_scientific_hash != SCIENTIFIC_BLOCK_SHA256:
    raise RuntimeError('The scientific protocol block differs from the preserved revised protocol.')
OUTPUT = args.output.expanduser().resolve()
try:
    OUTPUT.mkdir(parents=True, exist_ok=False)
except FileExistsError:
    parser.error('--output must be a new directory; previous results will not be overwritten.')
ROOT = OUTPUT / 'fixtures'
ROOT.mkdir()

# BEGIN UNCHANGED SCIENTIFIC PROTOCOL
BASE = 'Analytical fixture\n1\n4 0 0\n0 4 0\n0 0 4\nAl\n1\nDirect\n0.9 0 0\n'
POT = 'TITEL = PAW_PBE Al TEST\nVRHFIN =Al: test\nENMAX = 240.0;\nEnd of Dataset\n'
checks = []

def check(identifier, category, expectation):
    def register(fn):
        checks.append((identifier, category, expectation, fn))
        return fn
    return register

def folder(name):
    path = ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path

def poscar(name, text=BASE):
    path = folder(name) / 'POSCAR'
    path.write_text(text, encoding='utf-8')
    return path

def near(actual, expected, tolerance=1e-10):
    assert np.allclose(actual, expected, atol=tolerance, rtol=tolerance), f'Expected {expected!r}; observed {actual!r}'

def rejected(fn, exc_type=ValueError):
    try:
        fn()
    except exc_type as exc:
        return str(exc)
    raise AssertionError(f'Expected {exc_type.__name__}; input was accepted')

def prepared(name, scheduler='slurm'):
    root = folder(name)
    source = root / 'POSCAR'
    source.write_text(BASE, encoding='utf-8')
    lib = root / 'potentials' / 'Al'
    lib.mkdir(parents=True)
    (lib / 'POTCAR').write_text(POT, encoding='utf-8')
    target = root / 'calculation'
    api.prepare(source, target, preset='static', potcar_root=lib.parent, scheduler=scheduler)
    return target

@check('P01', 'POSCAR', 'Three Cartesian scale factors multiply columns of a skew lattice; Direct positions retain their fractional coordinates.')
def _():
    text = 'Skew\n2 3 4\n2 1 0\n0 3 1\n1 0 4\nAl\n1\nDirect\n.25 .5 .75\n'
    obj = Poscar.read(poscar('P01', text))
    near(obj.cell, [[4, 3, 0], [0, 9, 4], [2, 0, 16]])
    near(obj.fractional @ obj.cell, [[2.5, 5.25, 14]])
    return {'cartesian_angstrom': (obj.fractional @ obj.cell).tolist()}

@check('P02', 'POSCAR', 'Cartesian coordinates are scaled by the same three factors, even in a skew lattice.')
def _():
    text = 'Skew\n2 3 4\n2 1 0\n0 3 1\n1 0 4\nAl\n1\nCartesian\n1.25 1.75 3.5\n'
    obj = Poscar.read(poscar('P02', text))
    near(obj.fractional, [[.25, .5, .75]])
    return {'fractional': obj.fractional.tolist()}

@check('P03', 'POSCAR', 'A negative scalar denotes target volume: -1000 gives a 10-A cube from a raw 4-A cube.')
def _():
    obj = Poscar.read(poscar('P03', BASE.replace('\n1\n4', '\n-1000\n4')))
    near(obj.cell, np.eye(3) * 10)
    near(abs(np.linalg.det(obj.cell)), 1000)
    return {'volume_angstrom3': float(abs(np.linalg.det(obj.cell)))}

@check('P04', 'POSCAR', 'Incomplete selective dynamics flags are rejected.')
def _():
    path = poscar('P04', BASE.replace('Direct', 'Selective dynamics\nDirect').replace('0.9 0 0', '0.9 0 0 T F'))
    return {'error': rejected(lambda: Poscar.read(path))}

@check('P05', 'POSCAR', 'A purported chemical element Qq is rejected as an invalid element symbol.')
def _():
    return {'error': rejected(lambda: Poscar.read(poscar('P05', BASE.replace('\nAl\n', '\nQq\n'))))}

@check('N01', 'periodic displacement', 'For 64 reproducible skew-cell displacements, norms equal an independent integer-shift enumeration over [-8,8]^3.')
def _():
    cell = np.array([[4.0, 0, 0], [3.2, 1.1, 0], [.7, .4, 2.8]])
    delta = np.random.default_rng(20260928).uniform(-2, 2, (64, 3))
    shifts = np.array(list(itertools.product(range(-8, 9), repeat=3)))
    actual = np.linalg.norm(minimum_image(delta, cell) @ cell, axis=1)
    oracle = np.array([min(np.linalg.norm((row - shifts) @ cell, axis=1)) for row in delta])
    near(actual, oracle)
    return {'displacements': 64, 'oracle_shifts_per_displacement': len(shifts), 'maximum_absolute_distance_error_a': float(max(abs(actual - oracle)))}

@check('N02', 'periodic displacement', 'The minimum distance is invariant under arbitrary integer lattice translations.')
def _():
    cell = np.array([[3., 0, 0], [2., 2, 0], [1., 1, 4]])
    a = minimum_image(np.array([[.9, -.2, .6]]), cell)
    b = minimum_image(np.array([[.9, -.2, .6]]) + [[9, -3, 5]], cell)
    near(np.linalg.norm(a @ cell), np.linalg.norm(b @ cell))
    return {'distance_a': float(np.linalg.norm(a @ cell))}

@check('N03', 'periodic displacement', 'A near-singular cell is rejected rather than silently returning a numerical distance.')
def _():
    return {'error': rejected(lambda: minimum_image([[.2, .1, .4]], np.diag([1, 1, 1e-14])))}

def barrier_fixture(name, energies):
    root = folder(name)
    for index, energy in enumerate(energies):
        image = root / f'{index:02d}'
        image.mkdir()
        if energy is not None:
            (image / 'OUTCAR').write_text(f' free energy TOTEN = {energy} eV\n', encoding='utf-8')
    return neb_report(root)

@check('B01', 'NEB energy reporting', 'Synthetic image energies [-5,-4,-4.5] eV give forward/reverse barriers 1/0.5 eV, marked provisional.')
def _():
    report = barrier_fixture('B01', [-5, -4, -4.5])
    near(report['forward_barrier_ev'], 1)
    near(report['reverse_barrier_ev'], .5)
    assert 'provisional' in report['note']
    return {k: report[k] for k in ('forward_barrier_ev', 'reverse_barrier_ev', 'note')}

@check('B02', 'NEB energy reporting', 'A missing interior-image energy leaves both barriers null, even with both endpoint energies present.')
def _():
    report = barrier_fixture('B02', [-5, None, -4.5])
    assert report['forward_barrier_ev'] is None and report['reverse_barrier_ev'] is None
    assert not report['all_energies_available']
    return {'forward_barrier_ev': None, 'reverse_barrier_ev': None}

@check('B03', 'NEB energy reporting', 'A missing initial energy leaves every relative energy and both barriers null.')
def _():
    report = barrier_fixture('B03', [None, -4, -4.5])
    assert all(row['relative_energy_ev'] is None for row in report['images'])
    assert report['forward_barrier_ev'] is None and report['reverse_barrier_ev'] is None
    return {'relative_energies_ev': [row['relative_energy_ev'] for row in report['images']]}

@check('R01', 'result parsing', 'An OSZICAR-only calculation yields the last ionic free energy, Fortran D exponents, magnetization and electronic iteration.')
def _():
    root = folder('R01')
    (root / 'OSZICAR').write_text('DAV: 8 -2\n 1 F= -.300000D+01 E0= -3.1 mag= 1.5\nDAV: 4 -4\n 2 F= -.400000D+01 E0= -4.1 mag= 2.0\n', encoding='utf-8')
    obj = inspect_calculation(root)
    near(obj['energy_ev'], -4)
    near(obj['magnetization'], 2)
    assert obj['electronic_step'] == 4 and obj['ionic_steps'] == 2
    return {key: obj[key] for key in ('energy_ev', 'magnetization', 'electronic_step', 'ionic_steps')}

@check('R02', 'result parsing', 'If OUTCAR is empty and OSZICAR contains -4 eV, energy remains recoverable from OSZICAR.')
def _():
    root = folder('R02')
    (root / 'OUTCAR').write_text('', encoding='utf-8')
    (root / 'OSZICAR').write_text(' 1 F= -4.0 E0= -4.1\n', encoding='utf-8')
    obj = inspect_calculation(root)
    assert obj['energy_ev'] == -4., f"Expected OSZICAR fallback -4.0 eV; observed {obj['energy_ev']!r}"
    return {'energy_ev': obj['energy_ev']}

@check('R03v2', 'result parsing', 'An explicitly declared two-atom system with two force rows gives the maximum vector norm, and a normal exit alone does not prove convergence.')
def _():
    root = folder('R03v2')
    (root / 'OUTCAR').write_text(' number of ions NIONS = 2\n free energy TOTEN = -1 eV\n free energy TOTEN = -2D+00 eV\n POSITION TOTAL-FORCE (eV/Angst)\n -------\n 0 0 0 .03 .04 0\n 1 1 1 0 0 .08\n -------\n General timing and accounting informations for this job:\n', encoding='utf-8')
    obj = inspect_calculation(root)
    near(obj['energy_ev'], -2)
    near(obj['max_force_ev_a'], .08)
    assert obj['finished'] and not obj['ionic_converged'] and obj['electronic_convergence'] == 'not_assessed'
    return {key: obj[key] for key in ('energy_ev', 'max_force_ev_a', 'finished', 'ionic_converged', 'electronic_convergence')}

@check('R04', 'result parsing', 'A force block containing all known atoms followed by EOF still exposes its complete force norm.')
def _():
    root = folder('R04')
    (root / 'POSCAR').write_text(BASE, encoding='utf-8')
    (root / 'OUTCAR').write_text(' POSITION TOTAL-FORCE (eV/Angst)\n -------\n 0 0 0 .03 .04 0\n', encoding='utf-8')
    obj = inspect_calculation(root)
    assert obj['max_force_ev_a'] == .05, f"Expected 0.05 eV/A from one complete atom row; observed {obj['max_force_ev_a']!r}"
    return {'max_force_ev_a': obj['max_force_ev_a']}

@check('R05', 'result parsing', 'A truncated force block with fewer rows than POSCAR atoms must be marked incomplete or leave the maximum force unknown.')
def _():
    root = folder('R05')
    (root / 'POSCAR').write_text(BASE.replace('Al\n1\n', 'Al\n2\n') + '0.2 0.2 0.2\n', encoding='utf-8')
    (root / 'OUTCAR').write_text(' POSITION TOTAL-FORCE (eV/Angst)\n -------\n 0 0 0 .03 .04 0\n interrupted output\n', encoding='utf-8')
    obj = inspect_calculation(root)
    assert obj['max_force_ev_a'] is None or obj['warnings'], f"Expected null force or explicit incomplete-table warning for 1/2 atoms; observed max_force={obj['max_force_ev_a']!r}, warnings={obj['warnings']!r}"
    return {'max_force_ev_a': obj['max_force_ev_a'], 'warnings': obj['warnings']}

@check('R06', 'result parsing', 'A force table without POSCAR or NIONS cannot establish full-system completeness and therefore yields null maximum force plus a warning.')
def _():
    root = folder('R06')
    (root / 'OUTCAR').write_text(' POSITION TOTAL-FORCE (eV/Angst)\n -------\n 0 0 0 .03 .04 0\n 1 1 1 0 0 .08\n -------\n General timing and accounting informations for this job:\n', encoding='utf-8')
    obj = inspect_calculation(root)
    assert obj['max_force_ev_a'] is None, f"Expected unknown full-system maximum without independent atom count; observed {obj['max_force_ev_a']!r}"
    assert obj['warnings'], 'Expected a completeness warning when atom count is unavailable'
    return {'max_force_ev_a': obj['max_force_ev_a'], 'warnings': obj['warnings']}

@check('S01', 'mocked scheduler', 'Before a Slurm call, an on-disk unknown record exists; accepted response records job ID and a second call never invokes the scheduler.')
def _():
    root = prepared('S01')
    states = []
    def fake(argv, cwd=None, timeout=45):
        states.append(json.loads((root / '.iface-submission.json').read_text())['state'])
        return '4312;fixture_cluster'
    with patch('iface.scheduler.shutil.which', return_value='mock-sbatch'), patch('iface.scheduler._run', side_effect=fake) as invoke:
        report = submit(root, confirmed=True)
        assert states == ['unknown'] and report['job_id'] == '4312' and report['state'] == 'submitted'
        rejected(lambda: submit(root, confirmed=True))
        assert invoke.call_count == 1
    return {'state_observed_before_scheduler': states[0], 'final_state': report['state'], 'scheduler_calls': 1}

@check('S02', 'mocked scheduler', 'An unrecognized scheduler reply retains the unknown state and blocks duplicate submission.')
def _():
    root = prepared('S02')
    with patch('iface.scheduler.shutil.which', return_value='mock-sbatch'), patch('iface.scheduler._run', return_value='unrecognized response') as invoke:
        rejected(lambda: submit(root, confirmed=True), RuntimeError)
        record = json.loads((root / '.iface-submission.json').read_text())
        assert record['state'] == 'unknown'
        rejected(lambda: submit(root, confirmed=True))
        assert invoke.call_count == 1
    return {'final_state': 'unknown', 'scheduler_calls': 1}

@check('S03', 'mocked scheduler', 'PBS success records the server-qualified job ID; all external calls are mocked.')
def _():
    root = prepared('S03', scheduler='pbs')
    with patch('iface.scheduler.shutil.which', return_value='mock-qsub'), patch('iface.scheduler._run', return_value='782.server.example') as invoke:
        report = submit(root, scheduler='pbs', confirmed=True)
        assert report['job_id'] == '782.server.example' and report['state'] == 'submitted'
        assert invoke.call_args.args[0] == ['qsub', 'job.sh']
    return {'job_id': report['job_id'], 'state': report['state']}

def vibration_pair(name, saddle_flags='T T T'):
    root = folder(name)
    for state, flags, modes in [('initial', 'T T T', [(2, False), (3, False), (4, False)]),
                                ('saddle', saddle_flags, [(1, True), (5, False), (6, False)])]:
        target = root / state
        target.mkdir()
        structure = BASE.replace('Direct', 'Selective dynamics\nDirect').replace('0.9 0 0', '0.9 0 0 ' + flags)
        (target / 'POSCAR').write_text(structure, encoding='utf-8')
        rows = [f" {i} {'f/i' if imaginary else 'f'} = {value} THz" for i, (value, imaginary) in enumerate(modes, 1)]
        (target / 'OUTCAR').write_text('\n'.join(rows) + '\n General timing and accounting informations for this job:\n', encoding='utf-8')
    return root / 'initial', root / 'saddle'

@check('V01', 'harmonic frequency', 'A matched synthetic 3-mode fixture yields the analytical product ratio (2*3*4)/(5*6) = 0.8 THz.')
def _():
    initial, saddle = vibration_pair('V01')
    report = effective_frequency(initial, saddle)
    near(report['effective_frequency_thz'], .8)
    near(report['effective_frequency_hz'], 8e11)
    return {'effective_frequency_thz': report['effective_frequency_thz']}

@check('V02', 'harmonic frequency', 'A pair with 3 versus 1 active POSCAR degrees of freedom is rejected despite equal parsed frequency counts.')
def _():
    initial, saddle = vibration_pair('V02', 'T F F')
    try:
        report = effective_frequency(initial, saddle)
    except ValueError as exc:
        return {'rejection': str(exc)}
    raise AssertionError(f"Expected rejection of unequal active degrees of freedom (3 vs 1); returned prefactor {report['effective_frequency_thz']!r} THz")

# END UNCHANGED SCIENTIFIC PROTOCOL

results = []
for identifier, category, expectation, fn in checks:
    record = {'id': identifier, 'category': category, 'expectation': expectation}
    try:
        record['observed'] = fn()
        record['status'] = 'passed'
    except Exception as exc:
        record.update(status='failed', observed=str(exc), traceback=traceback.format_exc())
    results.append(record)
    print(f"{identifier} {record['status']}: {record['expectation']}")
    if record['status'] == 'failed':
        print('  ' + record['observed'])

versions = {}
for package in ['iface-linux', 'numpy', 'pymatgen', 'pymatgen-core', 'spglib', 'scipy', 'setuptools']:
    try:
        versions[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        versions[package] = None
package_root = imported_api_path.parent
installed_hashes = {path.relative_to(package_root.parent).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(package_root.rglob('*.py'))}
try:
    linux_distribution = platform.freedesktop_os_release()
except OSError:
    linux_distribution = {}
passed = sum(row['status'] == 'passed' for row in results)
failed = sum(row['status'] == 'failed' for row in results)
expected_ids = ['P01', 'P02', 'P03', 'P04', 'P05', 'N01', 'N02', 'N03', 'B01', 'B02', 'B03', 'R01', 'R02', 'R03v2', 'R04', 'R05', 'R06', 'S01', 'S02', 'S03', 'V01', 'V02']
if [row['id'] for row in results] != expected_ids:
    raise RuntimeError('The executed case list does not equal the preserved 22-case protocol.')
report = {
    'protocol': 'corrected-protocol-v2-public-reproduction',
    'report_kind': 'new execution using a public runner, not an original historical log',
    'timestamp_local': dt.datetime.now().astimezone().isoformat(),
    'execution': {'fixture_directory': str(ROOT), 'output_directory': str(OUTPUT),
                  'working_directory': str(Path.cwd()), 'argv': sys.argv},
    'environment': {'python': sys.version, 'python_executable': sys.executable, 'prefix': sys.prefix,
                    'os': platform.platform(), 'kernel_release': platform.release(), 'architecture': platform.machine(),
                    'linux_distribution': linux_distribution, 'packages': versions,
                    'imported_iface_path': str(Path(iface.__file__).resolve()), 'imported_api_path': str(imported_api_path),
                    'installed_distribution_version': distribution.version, 'installed_roots': [str(root) for root in installed_roots],
                    'site_packages_import_verified': True, 'distribution_file_match_verified': True,
                    'python_assertions_enabled': __debug__},
    'provenance': {'script_path': str(script_path), 'script_sha256': hashlib.sha256(script_path.read_bytes()).hexdigest(),
                   'upstream_corrected_protocol_script_sha256': ORIGIN_SCRIPT_SHA256,
                   'prior_linux_adaptation_script_sha256': LINUX_ADAPTATION_SCRIPT_SHA256,
                   'unchanged_scientific_block_sha256': actual_scientific_hash,
                   'installed_python_sources_sha256': installed_hashes,
                   'installed_source_manifest_sha256': hashlib.sha256(json.dumps(installed_hashes, sort_keys=True).encode()).hexdigest()},
    'independent_checks': {'total': len(results), 'passed': passed, 'failed': failed, 'skipped': 0, 'results': results},
    'protocol_groups': {
        'corrected_core': {'total': sum(row['id'] != 'R06' for row in results), 'passed': sum(row['id'] != 'R06' and row['status'] == 'passed' for row in results), 'failed': sum(row['id'] != 'R06' and row['status'] == 'failed' for row in results)},
        'added_no_atom_count_control': {'total': 1, 'passed': sum(row['id'] == 'R06' and row['status'] == 'passed' for row in results), 'failed': sum(row['id'] == 'R06' and row['status'] == 'failed' for row in results)}},
    'adaptation': {'scientific_assertions_and_fixtures_changed': False,
                   'infrastructure_changes': ['Require a new --output directory; keep fixtures inside it.', 'Require Linux virtual-environment site-packages imports; no source path insertion.', 'Reject disabled Python assertions and verify the protocol block before running cases.', 'Record only this new execution and its actual platform, dependencies, source hashes and reports.'],
                   'history_note': 'R03v2 declared NIONS=2 for its two force rows; R06 was added as the no-count control. The original 21-case protocol and historical logs remain separate evidence. This runner does not relabel those logs or count their results.'},
    'limits': ['This report concerns only the Linux environment recorded above.',
               'These 22 assertions use synthetic fixtures; they are not 22 physical benchmark systems.',
               'All scheduler calls are mocked; no real Slurm/PBS request is sent.',
               'No VASP executable, MPI computation or licensed POTCAR dataset is used.',
               'The separate regression suite, installer and CLI acceptance runs are not counted in this report.',
               'The finite skew-lattice oracle uses 64 deterministic displacements in one specified cell.']
}
(OUTPUT / 'offline_test_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
lines = ['# Independent protocol reproduction report', '',
         f'Observed result: **{passed}/{len(results)} passed**, {failed} failed, 0 skipped.', '',
         f"Installed iface version: {distribution.version}. Platform: {platform.platform()}.", '',
         'This is a new execution using the public runner, not an original historical log.', '',
         '## Environment and source identity', '',
         f'- Interpreter: `{sys.executable}`', f'- Imported API: `{imported_api_path}`',
         f'- Fixture directory: `{ROOT}`', '- Versions: ' + ', '.join(f'{key}={value}' for key, value in versions.items()),
         f"- Script SHA-256: `{report['provenance']['script_sha256']}`", f'- Scientific-block SHA-256: `{actual_scientific_hash}`', '',
         '## Observed cases', '', '| ID | Category | Status | Expectation |', '|---|---|---|---|']
lines.extend(f"| {row['id']} | {row['category']} | {row['status']} | {row['expectation']} |" for row in results)
lines.extend(['', '## Failures', ''])
if not failed:
    lines.append('No assertion failed in this execution.')
else:
    lines.extend(f"- {row['id']}: {row['observed']}" for row in results if row['status'] == 'failed')
lines.extend(['', '## Protocol and scope', '',
              'The scientific definitions, fixtures, numeric tolerances and assertions are unchanged from the revised 22-case protocol. Only execution paths, installed-package checks and reporting infrastructure were adapted for public reproduction. R03v2 contains the declared two-atom count; R06 is the separate no-count control.', '',
              *['- ' + item for item in report['limits']], ''])
(OUTPUT / 'offline_test_report.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'total': len(results), 'passed': passed, 'failed': failed, 'skipped': 0,
                  'imported_api': str(imported_api_path), 'report': str(OUTPUT / 'offline_test_report.json')}, indent=2))
raise SystemExit(1 if failed else 0)
