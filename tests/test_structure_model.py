import tempfile
import unittest
from pathlib import Path

from app.core.structure_model import (
    Atom,
    Structure,
    _parse_cif_atoms,
    load_structure,
    to_pymatgen_structure,
)


class StructureModelTests(unittest.TestCase):
    def test_extensionless_poscar_is_detected_by_content(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dragged_file"
            path.write_text(
                "Fe\n1.0\n2.8 0 0\n0 2.8 0\n0 0 2.8\n"
                "Fe\n1\nDirect\n0 0 0\n",
                encoding="utf-8",
            )
            structure = load_structure(path)
            self.assertEqual(len(structure.atoms), 1)
            self.assertEqual(structure.atoms[0].element, "Fe")

    def test_empty_structure_does_not_create_demo_atoms(self):
        structure = Structure()
        self.assertEqual(structure.name, "No structure loaded")
        self.assertEqual(structure.atoms, [])

    def test_invalid_file_never_falls_back_to_fake_nacl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.cif"
            path.write_text("this is not a structure", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_structure(path)

    def test_nonorthogonal_supercell_uses_full_lattice_vectors(self):
        structure = Structure(
            "triclinic",
            [Atom("Fe", 0.0, 0.0, 0.0)],
            ((2.0, 0.0, 0.0), (1.0, 3.0, 0.0), (0.5, 0.2, 4.0)),
        )
        structure.make_supercell(2, 2, 1)
        coordinates = {(atom.x, atom.y, atom.z) for atom in structure.atoms}
        self.assertIn((3.0, 3.0, 0.0), coordinates)
        self.assertEqual(structure.cell[0], (4.0, 0.0, 0.0))
        self.assertEqual(structure.cell[1], (2.0, 6.0, 0.0))

    def test_cif_partial_occupancy_opens_as_editable_structure(self):
        cif = """data_disordered
_cell_length_a 4.20
_cell_length_b 4.20
_cell_length_c 5.10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Fe1 Fe 0.0 0.0 0.0 0.5
Mn1 Mn 0.0 0.0 0.0 0.5
O1 O 0.333333 0.666667 0.25 1.0
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.cif"
            path.write_text(cif, encoding="utf-8")
            structure = load_structure(path)
            self.assertEqual(len(structure.atoms), 2)
            self.assertEqual(structure.atoms[0].element, "Fe")
            self.assertAlmostEqual(structure.cell[1][0], -2.1, places=5)

    def test_fallback_cif_uses_real_triclinic_cell_and_header_order(self):
        cif = """data_example
_cell_length_a 5.0(1)
_cell_length_b 6.0
_cell_length_c 7.0
_cell_angle_alpha 80
_cell_angle_beta 75
_cell_angle_gamma 70
loop_
_atom_site_fract_z
_atom_site_label
_atom_site_fract_x
_atom_site_type_symbol
_atom_site_fract_y
0.25 'Si1' 0.5 Si 0.125
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triclinic.cif"
            path.write_text(cif, encoding="utf-8")
            atoms, cell = _parse_cif_atoms(path)
            self.assertEqual(len(atoms), 1)
            self.assertEqual(atoms[0].element, "Si")
            self.assertAlmostEqual(cell[0][0], 5.0)
            self.assertNotEqual(cell[1][0], 0.0)
            self.assertNotEqual(cell[2][1], 0.0)

    def test_fallback_cif_expands_asymmetric_sites_to_full_conventional_cell(self):
        cif = """data_nacl
_cell_length_a 5.6402
_cell_length_b 5.6402
_cell_length_c 5.6402
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_name_H-M_alt 'F m -3 m'
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1 Na 0 0 0
Cl1 Cl 0.5 0.5 0.5
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nacl.cif"
            path.write_text(cif, encoding="utf-8")
            atoms, _cell = _parse_cif_atoms(path)
            self.assertEqual(len(atoms), 8)
            self.assertEqual(
                sum(atom.element == "Na" for atom in atoms),
                4,
            )
            self.assertEqual(
                sum(atom.element == "Cl" for atom in atoms),
                4,
            )

    def test_fallback_uses_explicit_symmetry_operations_without_spacegroup_database(self):
        cif = """data_inversion
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_space_group_symop_id
_space_group_symop_operation_xyz
1 'x,y,z'
2 '-x,-y,-z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.1 0.2 0.3
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inversion.cif"
            path.write_text(cif, encoding="utf-8")
            atoms, _cell = _parse_cif_atoms(path)
            self.assertEqual(len(atoms), 2)
            coordinates = {
                tuple(round(value, 3) for value in (atom.x, atom.y, atom.z))
                for atom in atoms
            }
            self.assertEqual(coordinates, {(0.5, 1.0, 1.5), (4.5, 4.0, 3.5)})

    def test_editing_species_does_not_export_stale_pymatgen_sites(self):
        structure = Structure(
            "editable",
            [Atom("Fe", 0.0, 0.0, 0.0, selected=True)],
            ((3.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 3.0)),
        )
        structure.replace_selected("Co")
        exported = to_pymatgen_structure(structure)
        self.assertEqual(exported[0].specie.symbol, "Co")


if __name__ == "__main__":
    unittest.main()
