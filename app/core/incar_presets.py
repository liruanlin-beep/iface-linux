"""Validated VASP 6.x INCAR presets used by every iface workflow."""

from collections import Counter


MAGNETIC_MOMENTS = {
    "Fe": 5.0, "Co": 3.0, "Ni": 2.0, "Mn": 5.0, "Cr": 5.0,
    "V": 3.0, "Ti": 2.0, "Cu": 1.0, "Gd": 7.0,
}


PRESET_LABELS = {
    "bulk_relax": 'Bulk alloy relaxation (spin-polarized)',
    "surface_interface_relax": 'Surface/interface relaxation (spin-polarized)',
    "static": 'Static self-consistency and total energy',
    "pdos": 'PDOS density of states',
    "bader": 'Bader input template (external Bader program required)',
    "charge_difference": 'Charge-difference static calculation',
    "neb": 'CI-NEB input template (image directories and VTST required)',
    "molecular_dynamics": 'Ab initio molecular dynamics',
    "vaspsol": 'VASPsol input template (compiled extension required)',
    "cohp": 'COHP preparation template (LOBSTER required)',
}


def magnetic_moments(elements):
    counts = Counter(str(value) for value in (elements or []))
    return " ".join(
        f"{counts[element]}*{MAGNETIC_MOMENTS.get(element, 1.0):g}"
        for element in counts
    )


def get_incar_preset(name, elements=None):
    common = {
        "PREC": "Accurate",
        "ENCUT": "520",
        "EDIFF": "1E-6",
        "ALGO": "Normal",
        "ISPIN": "2",
        "LASPH": ".TRUE.",
        "LREAL": "Auto",
        "NELM": "120",
    }
    moment = magnetic_moments(elements)
    if moment:
        common["MAGMOM"] = moment

    presets = {
        "bulk_relax": {
            **common, "SYSTEM": "alloy_bulk_relax", "EDIFFG": "-0.02",
            "IBRION": "2", "NSW": "150", "ISIF": "3",
            "ISMEAR": "1", "SIGMA": "0.20", "LWAVE": ".FALSE.",
            "LCHARG": ".FALSE.",
        },
        "surface_interface_relax": {
            **common, "SYSTEM": "surface_interface_relax", "EDIFFG": "-0.02",
            "IBRION": "2", "NSW": "200", "ISIF": "2",
            "ISMEAR": "1", "SIGMA": "0.20", "LDIPOL": ".TRUE.",
            "IDIPOL": "3", "LWAVE": ".FALSE.", "LCHARG": ".FALSE.",
        },
        "static": {
            **common, "SYSTEM": "static_energy", "EDIFF": "1E-7",
            "IBRION": "-1", "NSW": "0", "ISMEAR": "-5",
            "SIGMA": "0.05", "LREAL": ".FALSE.", "LWAVE": ".TRUE.",
            "LCHARG": ".TRUE.", "LAECHG": ".FALSE.",
        },
        "pdos": {
            **common, "SYSTEM": "pdos", "EDIFF": "1E-7",
            "IBRION": "-1", "NSW": "0", "ISMEAR": "-5",
            "SIGMA": "0.05", "LREAL": ".FALSE.", "ICHARG": "11",
            "LORBIT": "11", "NEDOS": "4001", "EMIN": "-15",
            "EMAX": "10", "LWAVE": ".FALSE.", "LCHARG": ".FALSE.",
        },
        "bader": {
            **common, "SYSTEM": "bader_charge", "EDIFF": "1E-7",
            "IBRION": "-1", "NSW": "0", "ISMEAR": "-5",
            "SIGMA": "0.05", "LREAL": ".FALSE.", "LCHARG": ".TRUE.",
            "LAECHG": ".TRUE.", "LWAVE": ".FALSE.",
        },
        "charge_difference": {
            **common, "SYSTEM": "charge_difference", "EDIFF": "1E-7",
            "IBRION": "-1", "NSW": "0", "ISMEAR": "0",
            "SIGMA": "0.05", "LREAL": ".FALSE.", "LCHARG": ".TRUE.",
            "LAECHG": ".FALSE.", "LWAVE": ".FALSE.",
        },
        "neb": {
            **common, "SYSTEM": "ci_neb", "EDIFFG": "-0.05",
            "IBRION": "3", "NSW": "500", "POTIM": "0",
            "ISIF": "2", "ISMEAR": "0", "SIGMA": "0.10",
            "ISYM": "0", "SPRING": "-5", "LCLIMB": ".TRUE.",
            "IOPT": "1", "LWAVE": ".FALSE.", "LCHARG": ".FALSE.",
        },
        "molecular_dynamics": {
            **common, "SYSTEM": "ab_initio_md", "EDIFF": "1E-5",
            "IBRION": "0", "NSW": "5000", "POTIM": "2.0",
            "ISIF": "2", "ISMEAR": "0", "SIGMA": "0.10",
            "ISYM": "0", "SMASS": "0", "TEBEG": "1000",
            "TEEND": "1000", "LWAVE": ".FALSE.", "LCHARG": ".FALSE.",
        },
        "vaspsol": {
            **common, "SYSTEM": "vaspsol_relax", "EDIFFG": "-0.02",
            "IBRION": "2", "NSW": "200", "ISIF": "2",
            "ISMEAR": "0", "SIGMA": "0.10", "LSOL": ".TRUE.",
            "EB_K": "80", "LAMBDA_D_K": "3.0", "TAU": "0",
            "LRHOION": ".TRUE.", "LWAVE": ".FALSE.", "LCHARG": ".FALSE.",
        },
        "cohp": {
            **common, "SYSTEM": "cohp_lobster", "EDIFF": "1E-7",
            "IBRION": "-1", "NSW": "0", "ISMEAR": "0",
            "SIGMA": "0.05", "ISYM": "-1", "LREAL": ".FALSE.",
            "LWAVE": ".TRUE.", "LCHARG": ".TRUE.",
        },
    }
    if name not in presets:
        raise ValueError(f'Unknown INCAR calculation type: {name}')
    return presets[name]


def render_incar_preset(name, elements=None):
    params = get_incar_preset(name, elements)
    return "\n".join(f"{key} = {value}" for key, value in params.items()) + "\n"
