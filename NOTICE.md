# Provenance and dependencies

The application in `app/` is the complete Linux adaptation of the author's
original iface Windows source. `WINDOWS_BASELINE.json` records that source's
file hashes. The original surface/interface algorithms, calculations, task
workflows and desktop controls are retained.

The earlier 3.x terminal edition exposed a subset of the Windows application.
Version 4.0 supersedes that edition with the original desktop functionality.
Reference software is not the feature specification. No VaspCZ, VTST or VASP
source code is bundled.

Python dependencies are installed separately and retain their respective
licenses. NumPy, pymatgen, Matplotlib, Pillow, Paramiko, tkinterdnd2 and keyring
are declared in `pyproject.toml`. Licensed VASP/POTCAR files, server credentials,
project databases, manuscripts and user research data are not distributed.
Examples and regression fixtures are illustrative or synthetic.
