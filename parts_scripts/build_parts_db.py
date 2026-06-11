"""Build a queryable parts dataset from the collected KSP `.cfg` files.

Walks `cfgs/`, parses every top-level `PART` node (skipping ModuleManager
patches like `@PART`), extracts identity/cost, physical, and resource fields,
derives provenance (source mod + family) from the file path, resolves
localization tokens, and writes `parts.ndjson` (one JSON object per line).

Usage:
    python3 scripts/build_parts_db.py
    python3 scripts/build_parts_db.py --cfgs cfgs --out parts.ndjson

Designed for Claude/skill consumption:
    grep '"name": "bluedog_Apollo_CM"' parts.ndjson
    jq -c 'select(.source=="Bluedog_DB" and .mass < 1)' parts.ndjson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import ksp_cfg
import part_modules
from ksp_cfg import Node
from util import to_float as _to_float, to_int as _to_int

# KSP stack/attach node size codes -> approximate metres, for reference.
SIZE_METRES = {0: 0.625, 1: 1.25, 2: 2.5, 3: 3.75, 4: 5.0}

# Localization dictionaries that ship with stock KSP and its DLCs. Tokens not
# found inline in a part file are resolved against these (merged in order).
_GAMEDATA = Path(
    "/mnt/c/Program Files/Epic Games/KerbalSpaceProgram/English/GameData"
)
DEFAULT_DICTS = [
    _GAMEDATA / "Squad/Localization/dictionary.cfg",
    _GAMEDATA / "SquadExpansion/Serenity/Localization/dictionary.cfg",
]


def _attach_sizes(part: Node) -> List[int]:
    """Collect the size code from each stack/attach node line.

    Node value format: posX,posY,posZ,dirX,dirY,dirZ[,size,...]. The 7th field
    (index 6) is the size code; absent means default 1 (1.25 m)."""
    sizes: List[int] = []
    for key, values in part.props.items():
        if not (key.startswith("node_stack") or key.startswith("node_attach")):
            continue
        for v in values:
            fields = [f.strip() for f in v.split(",")]
            size = _to_int(fields[6]) if len(fields) >= 7 else 1
            if size is not None:
                sizes.append(size)
    return sorted(set(sizes))


def _resources(part: Node) -> List[Dict[str, Optional[float]]]:
    """PART-level RESOURCE nodes only = storage capacity. RESOURCE nodes nested
    inside MODULE nodes are consumption/production rates and are intentionally
    excluded (they are not direct children of PART)."""
    out: List[Dict[str, Optional[float]]] = []
    for r in part.children_named("RESOURCE"):
        name = r.first("name")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "amount": _to_float(r.first("amount")),
                "maxAmount": _to_float(r.first("maxAmount")),
            }
        )
    return out


# Category values KSP uses to hide a part from the editor parts list.
_HIDDEN_CATEGORIES = {"none", "-1"}


def _is_buildable(part: Node, rel: Path) -> bool:
    """False for parts that never appear in the editor: Prebuilt kerbonauts
    and deprecated parts hidden via `category = none`/`-1`."""
    if "Prebuilt" in rel.parts:
        return False
    cat = (part.first("category") or "").strip().lower()
    return cat not in _HIDDEN_CATEGORIES


def _provenance(rel: Path) -> Dict[str, Optional[str]]:
    """First path segment = source mod; second = family/category dir."""
    parts = rel.parts
    source = parts[0] if parts else None
    family = parts[1] if len(parts) > 2 else None
    return {"source": source, "family": family, "path": rel.as_posix()}


def extract_part(part: Node, rel: Path, loc: List[Dict[str, str]]) -> Optional[Dict]:
    name = part.first("name")
    if not name:
        return None  # not a real part definition

    record: Dict[str, object] = {
        "name": name,
        "title": ksp_cfg.resolve(part.first("title"), *loc) or name,
        "manufacturer": ksp_cfg.resolve(part.first("manufacturer"), *loc),
        "description": ksp_cfg.resolve(part.first("description"), *loc),
        "buildable": _is_buildable(part, rel),
        **_provenance(rel),
        "category": part.first("category"),
        "subcategory": _to_int(part.first("subcategory")),
        "techRequired": part.first("TechRequired"),
        "crewCapacity": _to_int(part.first("CrewCapacity")),
        "cost": _to_float(part.first("cost")),
        "entryCost": _to_float(part.first("entryCost")),
        "mass": _to_float(part.first("mass")),
        "crashTolerance": _to_float(part.first("crashTolerance")),
        "maxTemp": _to_float(part.first("maxTemp")),
        "angularDrag": _to_float(part.first("angularDrag")),
        "maxDrag": _to_float(part.first("maximum_drag")),
        "minDrag": _to_float(part.first("minimum_drag")),
        "bulkheadProfiles": [
            p.strip()
            for p in (part.first("bulkheadProfiles") or "").split(",")
            if p.strip()
        ],
        "attachNodeSizes": _attach_sizes(part),
        "resources": _resources(part),
    }
    record.update(part_modules.extract(part))
    return record


def build(cfgs_dir: Path, out_path: Path, dict_paths: List[Path]) -> None:
    files = sorted(cfgs_dir.rglob("*.cfg"))
    if not files:
        sys.exit(f"No .cfg files found under {cfgs_dir}")

    # Pass 1: build localization maps (inline comments + stock dictionary).
    inline: Dict[str, str] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            print(f"WARN  could not read {f}: {e}", file=sys.stderr)
            continue
        ksp_cfg.collect_inline_localizations(text, inline)
    loc_maps = [inline] + [ksp_cfg.load_dictionary(d) for d in dict_paths]

    # Pass 2: parse parts and write records.
    records: List[Dict] = []
    parse_errors = 0
    for f in files:
        rel = f.relative_to(cfgs_dir)
        try:
            root = ksp_cfg.parse_file(f)
        except Exception as e:  # malformed file -> skip, keep going
            parse_errors += 1
            print(f"WARN  parse failed {rel}: {e}", file=sys.stderr)
            continue
        for part in root.children_named("PART"):
            rec = extract_part(part, rel, loc_maps)
            if rec:
                records.append(rec)

    records.sort(key=lambda r: (r["source"] or "", r["family"] or "", r["name"]))
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _summarize(records, out_path, parse_errors)


def _summarize(records: List[Dict], out_path: Path, parse_errors: int) -> None:
    by_source: Dict[str, int] = {}
    with_resources = non_buildable = 0
    for r in records:
        by_source[r["source"] or "?"] = by_source.get(r["source"] or "?", 0) + 1
        if r["resources"]:
            with_resources += 1
        if not r["buildable"]:
            non_buildable += 1
    print(f"Wrote {len(records)} parts -> {out_path}")
    for src, n in sorted(by_source.items()):
        print(f"  {src:<16} {n}")
    print(f"  parts with stored resources: {with_resources}")
    print(f"  non-buildable (flagged):     {non_buildable}")
    if parse_errors:
        print(f"  parse errors (skipped): {parse_errors}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cfgs", type=Path, default=Path("cfgs"))
    ap.add_argument("--out", type=Path, default=Path("parts.ndjson"))
    ap.add_argument("--dict", type=Path, nargs="*", default=DEFAULT_DICTS)
    args = ap.parse_args()
    build(args.cfgs, args.out, args.dict)


if __name__ == "__main__":
    main()
