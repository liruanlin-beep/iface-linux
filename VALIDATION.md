# Linux desktop validation — 4.0.0

The local acceptance environment is Ubuntu 24.04 under WSL2, Python 3.12.3,
Tk 8.6 and an Xvfb X11 display. Tests use a disposable Linux account and
isolated application data. Dependency versions are recorded in
`requirements-tested.txt`.

## Regression and source retention

- The complete suite runs 117 tests: 116 pass and one Windows-only DPAPI test
  is skipped on Linux. Linux secure storage has separate tests below.
- Original tests remain present. English message assertions were updated;
  Unicode input fixtures and scientific assertions were retained.
- The source-retention check covers all 68 original app files, 987 original
  declarations, original controls/events/tests, 15 computational module ASTs,
  all 10 parameter presets and all 19 Agent tool names/risk classifications.
- The only extra placeholder normalization permits English equivalents while
  requiring the original Chinese placeholder recognition to remain present.

Reproduce with:

```bash
python tools/verify_feature_parity.py --report parity-report.json
xvfb-run -a python -m unittest discover -s tests -v
```

## Installed application acceptance

The installed `iface --self-test` passes outside the source directory. It checks
fresh configuration and data isolation; POSCAR/CIF import; supercell generation;
input export; PNG/TIFF/PDF/SVG/XLSX output; queue/workflow recovery; main-window
construction; structure display; drag/drop initialization; and Tk callback errors.

The full installer also succeeds in a fresh user-owned environment whose path
contains spaces, creates the Applications launcher and icon, passes the installed
self-test, and passes `pip check`.

The queue simulation builds 48 workflows/176 tasks, dispatches 144 mock jobs,
prevents 48 duplicate tasks, respects its configured capacity of eight and
recovers two stale claims. Other regression tests cover the original default
ten-job capacity. These numbers describe simulated tests, not cluster throughput.

## GUI and Linux integration

An Xvfb smoke run imports and edits synthetic Al structures, generates surfaces
and interface candidates, visits the viewer, structure tools, interface builder,
high-throughput tabs, task center, post-processing tabs, settings, AI window,
SSH windows and input dialogs, and captures their display. No real remote
connection or paid API call is used. The GUI run records callback errors and
checks visible text; screenshots are included under `docs/screenshots`.
The final run passes all 15 steps with zero callback errors, no visible
untranslated Chinese text and no automatically detected label clipping.

Native Secret Service integration was tested with a private D-Bus session and
disposable GNOME Keyring: save/read succeeds, configuration contains only a
reference, replacement deletes the previous secret, and removal is idempotent.
The tests do not read or alter a real user's credential store.

Linux path handling, editor/terminal argument construction, English remote
folder status handling, disconnected-task retry behavior and X11 scrolling
have focused regression tests. Drag/drop registration and importing local
files are exercised; desktop file-manager drag gestures and external editor
applications still depend on the target desktop session.

## CI and limits

The GitHub Actions workflow installs the package on Ubuntu 24.04, repeats the
feature-retention check and regression suite, launches installed acceptance
under Xvfb and builds the source/wheel artifacts. The workflow publishes its
acceptance reports.

No real VASP executable, licensed potential library, production SSH/Slurm
server, live DeepSeek response or physical scientific result was validated in
this release procedure. Those workflows retain the Windows implementation;
their local state/queue/input behavior is tested with fixtures and mocks.
An Xvfb run cannot certify every mouse gesture or every Linux desktop theme.
The provided evidence supports the tested Linux port and identifies these
remaining environment-dependent checks explicitly.
