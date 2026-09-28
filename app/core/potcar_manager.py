from pathlib import Path

from app.core.path_utils import normalize_local_path


class PotcarManager:
    """Find and concatenate VASP POTCAR files from a configured PAW root."""

    def __init__(self, potcar_root):
        self.root_text = normalize_local_path(potcar_root or "")
        configured_root = Path(self.root_text) if self.root_text else None
        self.root = self._resolve_library_root(configured_root)

    @staticmethod
    def _resolve_library_root(configured_root):
        if not configured_root or not configured_root.is_dir():
            return configured_root
        # Common archive layout: selected folder/paw_pbe/Fe/POTCAR.
        nested = configured_root / configured_root.name
        if nested.is_dir() and any(nested.glob("*/POTCAR")):
            return nested
        named_nested = configured_root / "paw_pbe"
        if named_nested.is_dir() and any(named_nested.glob("*/POTCAR")):
            return named_nested
        return configured_root

    def _check_root(self):
        if not self.root_text:
            raise FileNotFoundError('POTCAR root is not configured.')
        if not self.root or not self.root.exists():
            raise FileNotFoundError(f'POTCAR root does not exist: {self.root}')
        if not self.root.is_dir():
            raise FileNotFoundError(f'POTCAR path is not a directory: {self.root}')

    def find_for_element(self, element):
        self._check_root()
        element = str(element).strip()
        candidates = [
            self.root / element / "POTCAR",
            self.root / f"{element}_sv" / "POTCAR",
            self.root / f"{element}_pv" / "POTCAR",
            self.root / f"{element}_GW" / "POTCAR",
            self.root / f"POTCAR_{element}",
            self.root / f"{element}.POTCAR",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        lower = element.lower()
        for folder in self.root.iterdir():
            if folder.is_dir() and folder.name.lower().startswith(lower):
                potcar = folder / "POTCAR"
                if potcar.is_file():
                    return potcar
        return None

    def match_elements(self, elements):
        matches = []
        missing = []
        for element in elements:
            found = self.find_for_element(element)
            matches.append((element, found))
            if not found:
                missing.append(element)
        return matches, missing

    def build_potcar(self, elements, output_path):
        matches, missing = self.match_elements(elements)
        if missing:
            raise FileNotFoundError(
                'POTCAR not found for these elements: '
                + ", ".join(missing)
                + f'\nCurrent POTCAR root: {self.root}'
            )
        chunks = [path.read_bytes().rstrip() for _element, path in matches]
        Path(output_path).write_bytes(b"\n".join(chunks) + b"\n")
        return matches
