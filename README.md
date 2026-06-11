# KSP Parts Reference

A queryable dataset of every part in a specific Kerbal Space Program install (stock + both DLCs + Bluedog Design Bureau), built by parsing the game's `.cfg` files into one NDJSON file. It exists to support the `playing-ksp` Claude skill and to answer "which part has the best X" questions the in-game editor search can't.

**Output:** `parts.ndjson` — 1,768 parts, one JSON object per line (~1.5 MB).

## Layout

```
cfgs/                       # .cfg files COPIED from the game (provenance in the path)
  Squad/                    #   stock parts (359 cfgs)
  MakingHistory/            #   Making History DLC (71)
  Serenity/                 #   Breaking Ground DLC (60)
  Bluedog_DB/               #   BDB, organized by rocket family (Apollo, Atlas, Saturn, ...) (1419)
scripts/
  ksp_cfg.py               # brace parser for the ConfigNode format + localization resolver
  part_modules.py          # MODULE/function extraction (engines, power, parachutes, aero)
  util.py                  # number coercion helpers
  build_parts_db.py        # entry point: walk cfgs/ -> parts.ndjson
parts.ndjson               # the dataset (generated)
```

The `cfgs/` files are **copies**, not moves; the game install is untouched. The first path segment encodes the source mod and, for BDB, the second encodes the NASA-counterpart rocket family.

## Build pipeline

```bash
python3 scripts/build_parts_db.py
```

1. **Walk** every `.cfg` under `cfgs/`.
2. **Parse** each file's brace-delimited nodes (BOM/CRLF handled).
3. **Extract** every top-level `PART` node, skipping ModuleManager patches (`@PART`).
4. **Resolve** `#autoLOC_*` localization tokens via inline comments + the stock/Serenity `dictionary.cfg` files.
5. **Derive** `source` / `family` from the path and a `buildable` flag.
6. **Write** sorted records to `parts.ndjson` and print a summary.

Re-run after changing the contents of `cfgs/` (e.g. a mod update). Source `.cfg` directories the dataset was built from are listed at the top of `scripts/build_parts_db.py`.

## Schema

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Internal part id (exact lookup key) |
| `title`, `manufacturer`, `description` | string | Localized display fields |
| `buildable` | bool | `false` (54 parts) = kerbonauts (`Prebuilt/*`) or deprecated/hidden (`category` `none`/`-1`, incl. BDB `*Upgrade` stand-ins). Nothing is dropped; filter on this. |
| `source` | string | `Squad`, `MakingHistory`, `Serenity`, `Bluedog_DB` |
| `family`, `path` | string | Provenance from the path |
| `category`, `subcategory`, `techRequired`, `crewCapacity` | | Editor / tech-tree metadata |
| `cost`, `entryCost` | number | Funds |
| `mass`, `crashTolerance`, `maxTemp`, `angularDrag`, `maxDrag`, `minDrag` | number | Physical |
| `bulkheadProfiles` | [string] | e.g. `["size1"]` |
| `attachNodeSizes` | [int] | Size codes: 0=0.625m, 1=1.25m, 2=2.5m, 3=3.75m, 4=5m |
| `resources` | [obj] | Stored capacity: `{name, amount, maxAmount}` (storage only, not consumption rates) |
| `engines` | [obj] | Per mode: `{maxThrust, minThrust, ispVac, ispAsl, heatProduction, propellants}`. Omitted if not an engine. |
| `command`, `reactionWheel`, `power`, `parachute`, `aeroSurface` | obj | Function modules; each omitted when absent |

`resources` and `engines` are always present (as `[]` when empty); the other module objects are omitted entirely when the part lacks that module, to keep lines lean.

## Querying

`jq` for filters, `grep` for exact lookups:

```bash
DB=parts.ndjson
grep '"name": "liquidEngine2_v2"' "$DB" | jq          # one part
jq -c 'select(.buildable and .source=="Bluedog_DB" and (.engines|length>0))' "$DB"
```

A fuller cookbook of recipes (engine selection, TWR/Δv inputs, tank capacity, tech-node lookups) and important caveats lives in the skill reference doc:
`~/.claude/skills/playing-ksp/reference/parts-database.md`.

## Data caveats

These are the **raw cfg values as shipped**, before runtime ModuleManager patches from other mods. For the `playing-ksp` loadout specifically:

- **Jet engines** report misleading huge `ispVac` (air-breathing `atmosphereCurve`). Identify via an `IntakeAir` propellant and exclude them from Δv comparisons.
- **RealChute** overrides stock `parachute` behavior; **System Heat** overrides `heatProduction` / `maxTemp`; **CTT** reorganizes the tree so `techRequired` is the declared node, not always its CTT placement.
- Always filter `buildable:true` for "what should I build" answers.
- When a number is mission-critical, verify in the VAB / KER.
