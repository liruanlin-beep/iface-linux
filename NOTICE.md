# Provenance and acknowledgements

## Original iface application

iface for Linux adapts the author's earlier iface surface/interface application.
The slab, interface, structure and element-colour engines in `iface/core/` come
from `v2.0/app/core`, with English built-in messages. Layer/gap scans follow the
original independent-layer workflow. Surface-energy arithmetic follows the
original `result_analysis.calculate_surface_energy` implementation.

## Operating-style reference

VaspCZ was supplied as a reference for Linux terminal operation, not as the
required feature specification of iface:

Zhang Z, Tan M, Ren C, Huai P. VaspCZ: an efficient VASP computation assistant
program. Nuclear Techniques, 2020, 43(3): 030501.
https://doi.org/10.11889/j.0253-3219.2020.hjs.43.030501

No VaspCZ, VTST or VASP source code is bundled. Results and performance claims
of reference software are not validation of this application.

## Dependencies and data

NumPy, pymatgen and their dependencies are installed separately and retain their
own licences. Consult the licence files of the versions you install. VASP and
licensed potential datasets are not redistributed. Geometry examples and parser
fixtures are illustrative/synthetic; they are not electronic-structure results.
