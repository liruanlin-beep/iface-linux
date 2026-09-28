import hashlib


DEFAULT_ELEMENT_COLORS = {
    "H": "#FFFFFF",
    "C": "#333333",
    "O": "#E53935",
    "N": "#3F51B5",
    "Al": "#9EC9E6",
    "Y": "#2E7D68",
    "Ce": "#8E7CC3",
    "Zr": "#7DA7C9",
    "Fe": "#B5651D",
    "Si": "#F4D03F",
    "Mg": "#A9DFBF",
    "Ti": "#9E9E9E",
    "Cu": "#B87333",
    "Zn": "#7E57C2",
    "Na": "#7E86C7",
    "Cl": "#69A85A",
    "Li": "#CC80FF",
    "Be": "#C2FF00",
    "B": "#FFB5B5",
    "F": "#90E050",
    "P": "#FF8000",
    "S": "#FFFF30",
    "K": "#8F40D4",
    "Ca": "#3DFF00",
    "Mn": "#9C7AC7",
    "Co": "#F090A0",
    "Ni": "#50D050",
}

FALLBACK_PALETTE = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", "#8C564B",
    "#E377C2", "#17BECF", "#BCBD22", "#006D77", "#C1121F", "#588157",
    "#3A86FF", "#FB5607", "#8338EC", "#FF006E", "#118AB2", "#06D6A0",
]


class ElementColorManager:
    def __init__(self, custom_colors=None):
        self.colors = dict(DEFAULT_ELEMENT_COLORS)
        if custom_colors:
            self.colors.update(custom_colors)

    def color(self, element):
        if element not in self.colors:
            digest = hashlib.sha256(element.encode("utf-8")).digest()
            self.colors[element] = FALLBACK_PALETTE[digest[0] % len(FALLBACK_PALETTE)]
        return self.colors[element]


DEFAULT_COLOR_MANAGER = ElementColorManager()


def get_element_color(element):
    return DEFAULT_COLOR_MANAGER.color(element)
