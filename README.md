# KSP Parts Reference

A queryable dataset of every part in a specific Kerbal Space Program install (stock + both DLCs + Bluedog Design Bureau), built by parsing the game's `.cfg` files into one NDJSON file. It exists to support KSP related Claude skills and to answer "which part has the best X" questions the in-game editor search can't.

**Output:** `parts.ndjson` — 1,768 parts, one JSON object per line (~1.5 MB).

## Layout

```
cfgs/                       # .cfg files COPIED from the game (provenance in the path)
  Squad/                    #   stock parts (359 cfgs)
  MakingHistory/            #   Making History DLC (71)
  Serenity/                 #   Breaking Ground DLC (60)
  Bluedog_DB/               #   BDB, organized by rocket family (Apollo, Atlas, Saturn, ...) (1419)
parts_scripts/
  ksp_cfg.py               # brace parser for the ConfigNode format + localization resolver
  part_modules.py          # MODULE/function extraction (engines, power, antenna, parachutes, aero)
  util.py                  # number coercion helpers
  build_parts_db.py        # entry point: walk cfgs/ -> parts.ndjson
parts.ndjson               # the dataset (generated)
kos_scripts/               # unrelated: kOS script workspace
```

The `cfgs/` files are **copies**, not moves; the game install is untouched. The first path segment encodes the source mod and, for BDB, the second encodes the NASA-counterpart rocket family.

## Build pipeline

```bash
python3 parts_scripts/build_parts_db.py
```

1. **Walk** every `.cfg` under `cfgs/`.
2. **Parse** each file's brace-delimited nodes (BOM/CRLF handled).
3. **Extract** every top-level `PART` node, skipping ModuleManager patches (`@PART`).
4. **Resolve** `#autoLOC_*` localization tokens via inline comments + the stock/Serenity `dictionary.cfg` files.
5. **Derive** `source` / `family` from the path and a `buildable` flag.
6. **Write** sorted records to `parts.ndjson` and print a summary.

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
| `mass`, `crashTolerance`, `maxTemp`, `angularDrag`, `maxDrag`, `minDrag` | number | Physical. `mass` is dry mass (tonnes). |
| `resourceMass`, `wetMass` | number | Derived: stored-resource mass (Σ `maxAmount`×density) and `mass`+`resourceMass`. For tanks, `wetMass` is full mass; the rocket equation wants wet/dry = `wetMass`/`mass`. |
| `bulkheadProfiles` | [string] | Diameter profile(s), the reliable diameter signal. Stock `size0/1/2/3` = 0.625/1.25/2.5/3.75m; BDB `size#p#` = literal metres (`size2p5`=2.5m, `size00`=0.3125m) |
| `attachNodeSizes` | [int] | Stack node size codes. Stock/DLC: 0=0.625m, 1=1.25m, 2=2.5m, 3=3.75m, 4=5m. **Not reliable diameter for BDB** (codes mean attachment compatibility) — use `bulkheadProfiles` |
| `resources` | [obj] | Stored capacity: `{name, amount, maxAmount}` (storage only, not consumption rates) |
| `engines` | [obj] | Per mode: `{maxThrust, minThrust, ispVac, ispAsl, heatProduction, propellants}`. Omitted if not an engine. |
| `command`, `reactionWheel`, `power`, `antenna`, `parachute`, `aeroSurface` | obj | Function modules; each omitted when absent. `antenna.type` is INTERNAL / DIRECT / RELAY (relay sats need RELAY). |

`resources` and `engines` are always present (as `[]` when empty); the other module objects are omitted entirely when the part lacks that module, to keep lines lean.

## Querying

`jq` for filters, `grep` for exact lookups:

```bash
DB=parts.ndjson
grep '"name": "liquidEngine2_v2"' "$DB" | jq          # one part
jq -c 'select(.buildable and .source=="Bluedog_DB" and (.engines|length>0))' "$DB"
```

## Data caveats

These are the **raw cfg values as shipped**, before runtime ModuleManager patches from other mods. For the `playing-ksp` loadout specifically:

- **Jet engines** report misleading huge `ispVac` (air-breathing `atmosphereCurve`). Identify via an `IntakeAir` propellant and exclude them from Δv comparisons.
- **BDB diameters:** filter on `bulkheadProfiles`, not `attachNodeSizes`. BDB node-size integers mean attachment compatibility, not stock metres (a 0.3125m BDB part reports node size `1`).
- **RealChute** overrides stock `parachute` behavior; **System Heat** overrides `heatProduction` / `maxTemp`; **CTT** reorganizes the tree so `techRequired` is the declared node, not always its CTT placement.
- Always filter `buildable:true` for "what should I build" answers.
- When a number is mission-critical, verify in the VAB / KER.
