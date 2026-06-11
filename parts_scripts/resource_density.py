"""Parse KSP RESOURCE_DEFINITION densities from the game's resource cfgs.

Density is in tonnes per unit (e.g. LiquidFuel = 0.005 = 5 kg/unit). Used to
turn a part's stored `resources` (maxAmount per resource) into a real mass, so
the dataset can carry `resourceMass` and `wetMass` for Δv / TWR math.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import ksp_cfg
from util import to_float


def load_densities(paths: List[Path]) -> Dict[str, float]:
    """Merge RESOURCE_DEFINITION name->density from each cfg path.

    Earlier files win on conflict, so list stock before mod packs."""
    densities: Dict[str, float] = {}
    for path in paths:
        if not path.is_file():
            continue
        root = ksp_cfg.parse_file(path)
        for node in root.children_named("RESOURCE_DEFINITION"):
            name = node.first("name")
            density = to_float(node.first("density"))
            if name and density is not None:
                densities.setdefault(name, density)
    return densities
