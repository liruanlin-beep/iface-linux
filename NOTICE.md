# Sources and acknowledgements

## iface implementation

This repository publishes the Linux terminal edition of the author's iface
project. The slab, interface, structure and element-colour modules in
`iface/core/` were adapted from the same project's earlier `v2.0/app/core`
implementation. Their built-in messages were translated into English.
The desktop application and its local history are not part of this distribution.

## Workflow reference

The OS / NEB / Test grouping was informed by the published VaspCZ workflow:

Zhang Z, Tan M, Ren C, Huai P. VaspCZ: an efficient VASP computation assistant
program. Nuclear Techniques, 2020, 43(3): 030501.
https://doi.org/10.11889/j.0253-3219.2020.hjs.43.030501

Reference repository: https://github.com/zhangzhengde0225/VaspCZ

iface is an independent implementation, not a VaspCZ distribution. No VaspCZ,
VTST or VASP source code is bundled. The cited program's results, figures and
performance claims are not iface validation results. This reference does not
imply endorsement by its authors.

## Dependencies

Dependencies are installed separately and retain their own licences:

- NumPy: https://numpy.org/doc/stable/license.html
- pymatgen: https://github.com/materialsproject/pymatgen/blob/master/LICENSE
- spglib: https://github.com/spglib/spglib/blob/develop/COPYING

Consult the licence files shipped with the exact installed dependency versions,
including notices for bundled binary components. Dependency wheels and their
embedded libraries are not redistributed in the iface source release.

## Scientific software and example data

VASP is separate software. Users must obtain their own executable and required
pseudopotential datasets under the applicable terms. No such binaries or
licensed POTCAR datasets are distributed here. The few POTCAR-like strings in
tests are fabricated metadata marked TEST; they cannot be used for a calculation.

The example Al structures are generated geometric examples. Parser fixtures are
synthetic. Neither is evidence of a completed electronic-structure calculation.
