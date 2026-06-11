"""Extract function-relevant MODULE data from a parsed KSP PART node.

Covers the categories chosen for the dataset: engines (thrust + Isp),
power & command (EC generation, reaction-wheel torque, command), and
parachutes/aero. Comms and science modules are intentionally not extracted.

Each function returns plain JSON-serializable values; absent modules yield
`None` (or `[]` for engines) so the builder can omit empty keys, keeping the
NDJSON lean.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ksp_cfg import Node
from util import to_float

ENGINE_MODULES = {"ModuleEngines", "ModuleEnginesFX"}


def _modules(part: Node, *type_names: str) -> List[Node]:
    """All MODULE child nodes whose `name =` matches one of `type_names`."""
    return [
        m
        for m in part.children_named("MODULE")
        if m.first("name") in type_names
    ]


def _isp_from_curve(engine: Node) -> Dict[str, Optional[float]]:
    """Read vacuum/sea-level Isp from an engine's atmosphereCurve.

    Curve keys look like `key = <atm> <isp> [tangents...]`; atm 0 = vacuum,
    atm 1 = sea level (1 atmosphere)."""
    isp = {"ispVac": None, "ispAsl": None}
    curves = engine.children_named("atmosphereCurve")
    if not curves:
        return isp
    for key in curves[0].props.get("key", []):
        fields = key.split()
        if len(fields) < 2:
            continue
        atm, val = to_float(fields[0]), to_float(fields[1])
        if atm == 0:
            isp["ispVac"] = val
        elif atm == 1:
            isp["ispAsl"] = val
    return isp


def engines(part: Node) -> List[Dict]:
    """One entry per engine module (multi-mode engines have several)."""
    out: List[Dict] = []
    for e in _modules(part, *ENGINE_MODULES):
        propellants = [
            {"name": p.first("name"), "ratio": to_float(p.first("ratio"))}
            for p in e.children_named("PROPELLANT")
            if p.first("name")
        ]
        entry = {
            "maxThrust": to_float(e.first("maxThrust")),
            "minThrust": to_float(e.first("minThrust")),
            "heatProduction": to_float(e.first("heatProduction")),
            "propellants": propellants,
        }
        entry.update(_isp_from_curve(e))
        out.append(entry)
    return out


def command(part: Node) -> Optional[Dict]:
    mods = _modules(part, "ModuleCommand")
    if not mods:
        return None
    m = mods[0]
    return {
        "minimumCrew": to_float(m.first("minimumCrew")),
        "hibernation": (m.first("hasHibernation") or "False").lower() == "true",
    }


def reaction_wheel(part: Node) -> Optional[Dict]:
    mods = _modules(part, "ModuleReactionWheel")
    if not mods:
        return None
    m = mods[0]
    return {
        "pitch": to_float(m.first("PitchTorque")),
        "yaw": to_float(m.first("YawTorque")),
        "roll": to_float(m.first("RollTorque")),
    }


def _ec_output(node: Node, container: str) -> Optional[float]:
    """Sum ElectricCharge `rate` across a node's named output sub-nodes."""
    total = None
    for r in node.children_named(container):
        if r.first("name") == "ElectricCharge":
            rate = to_float(r.first("rate"))
            if rate is not None:
                total = (total or 0.0) + rate
    return total


def power(part: Node) -> Optional[Dict]:
    """Electric-charge generation broken out by source, since each has
    different conditions (sunlight / always-on / engine-running)."""
    result: Dict[str, float] = {}

    solar = sum(
        to_float(m.first("chargeRate")) or 0.0
        for m in _modules(part, "ModuleDeployableSolarPanel")
    )
    if solar:
        result["solarChargeRate"] = solar

    for m in _modules(part, "ModuleGenerator"):  # RTGs, always-on
        ec = _ec_output(m, "OUTPUT_RESOURCE")
        if ec:
            result["generatorEC"] = result.get("generatorEC", 0.0) + ec

    for m in _modules(part, "ModuleResourceConverter"):  # fuel cells
        ec = _ec_output(m, "OUTPUT_RESOURCE")
        if ec:
            result["converterEC"] = result.get("converterEC", 0.0) + ec

    for m in _modules(part, "ModuleAlternator"):  # engine-driven, while firing
        ec = _ec_output(m, "RESOURCE")
        if ec:
            result["alternatorEC"] = result.get("alternatorEC", 0.0) + ec

    return result or None


def parachute(part: Node) -> Optional[Dict]:
    mods = _modules(part, "ModuleParachute")
    if not mods:
        return None
    m = mods[0]
    return {
        "fullyDeployedDrag": to_float(m.first("fullyDeployedDrag")),
        "semiDeployedDrag": to_float(m.first("semiDeployedDrag")),
        "deployAltitude": to_float(m.first("deployAltitude")),
        "minAirPressureToOpen": to_float(m.first("minAirPressureToOpen")),
    }


def aero_surface(part: Node) -> Optional[Dict]:
    """Control surfaces and fixed lifting surfaces (wings/fins)."""
    ctrl = _modules(part, "ModuleControlSurface")
    lift = _modules(part, "ModuleLiftingSurface")
    if not ctrl and not lift:
        return None
    out: Dict[str, object] = {}
    if ctrl:
        out["controllable"] = True
        out["deflectionLiftCoeff"] = to_float(ctrl[0].first("deflectionLiftCoeff"))
        out["ctrlSurfaceRange"] = to_float(ctrl[0].first("ctrlSurfaceRange"))
    elif lift:
        out["controllable"] = False
        out["deflectionLiftCoeff"] = to_float(lift[0].first("deflectionLiftCoeff"))
    return out


def extract(part: Node) -> Dict[str, object]:
    """Return only the function fields that are present for this part."""
    fields: Dict[str, object] = {}
    eng = engines(part)
    if eng:
        fields["engines"] = eng
    for key, value in (
        ("command", command(part)),
        ("reactionWheel", reaction_wheel(part)),
        ("power", power(part)),
        ("parachute", parachute(part)),
        ("aeroSurface", aero_surface(part)),
    ):
        if value is not None:
            fields[key] = value
    return fields
