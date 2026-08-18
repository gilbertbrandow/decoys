# decoys

A pipeline for generating chess decoy puzzles from OTB master games and Lichess engine evaluations.

A **decoy puzzle** presents a balanced middlegame position where the player must find one of several equally-good continuations — there is no single "only move". They are the opposite of tactics: the test is calm assessment, not calculation. This pipeline identifies those positions automatically from master game databases.

The output is a JSONL file (`decoy_positions.jsonl`) that can be imported into any chess training system. The schema is versioned and documented in [`schema.json`](schema.json). The canonical published dataset and its download URL are described in [`meta.json`](meta.json).

---

## How it works

**Stage 1 — Build the eval index**

Reads the [Lichess bulk eval dataset](https://database.lichess.org/#evals) (`lichess_db_eval.jsonl.zst`) and filters it into a local SQLite database of qualifying positions. A position qualifies when:

- Engine depth ≥ 20
- Best eval within ±200 centipawns (roughly equal)
- 3–6 moves cluster within 30 CP of the best move (multiple good options)
- The first move outside the cluster drops ≥ 50 CP (clear cliff below the cluster)

**Stage 2 — Scan master games**

Walks an OTB master PGN archive (both players ELO ≥ 2600) and looks up each position in the SQLite. When a match is found, the position is emitted as a puzzle record — including the opponent's last move, all accepted replies, and optionally a Lichess reference game URL. Positions are deduplicated across games by FEN.

---

## Quickstart (Docker)

```bash
# 1. Place your data files
mkdir -p data/raw
# data/raw/lichess_db_eval.jsonl.zst  (from database.lichess.org)
# data/raw/LumbrasGigaBase_OTB_ELITE_ELO2400.7z  (or any OTB master PGN)

# 2. Build the eval index (~hours, one-time)
make docker-build-evals

# 3. Scan games and produce the JSONL
make docker-scan-games

# Output: data/decoy_positions.jsonl
```

To publish to HuggingFace:

```bash
pip install -r requirements-publish.txt
make docker-publish HF_REPO=yourname/your-dataset
```

---

## Quickstart (local Python)

```bash
pip install -r requirements.txt

python build_evals.py \
  --src data/raw/lichess_db_eval.jsonl.zst \
  --out data/decoy_evals.sqlite

python run_scan.py \
  --games data/raw/LumbrasGigaBase_OTB_ELITE_ELO2400.7z \
  --db    data/decoy_evals.sqlite \
  --out   data/decoy_positions.jsonl \
  --sort-by-elo \
  --min-both-elo 2600
```

---

## Configuration

| Flag | Default | Description |
|---|---|---|
| `--min-both-elo` | 2600 | Minimum ELO for both players |
| `--sort-by-elo` | off | Process highest-rated games first |
| `--max-per-game` | 2 | Max decoy positions to emit per game |
| `--decoys-limit` | none | Stop after N decoys found |
| `--no-lichess-urls` | off | Skip Lichess reference URL lookup (faster) |
| `--event-filter` | none | Only include games whose Event header matches |

---

## Schema

Each line of `decoy_positions.jsonl` is a JSON object. The full schema is in [`schema.json`](schema.json).

**Required fields:**

| Field | Type | Description |
|---|---|---|
| `fen` | string | 4-part FEN before the opponent's move |
| `opponentMove` | string | UCI of the move that creates the puzzle position |
| `bestCp` | integer | Centipawns of the best reply (normalised to side to move) |
| `depth` | integer | Engine depth of the evaluation |
| `acceptedMoves` | array | All moves within cluster — any one is correct |
| `moveNumber` | integer | Half-move number in the source game |

Each entry in `acceptedMoves`: `{uci, line, cp, dropCp}`

**Optional fields:** `source`, `event`, `date`, `white`, `black`, `whiteElo`, `blackElo`, `whiteTitle`, `blackTitle`, `eco`, `openingName`, `lichessGameUrl`

---

## Schema versioning

`meta.json` contains the current `schemaVersion`. Consumers should check this before importing to detect breaking changes:

```python
import requests, json

meta = requests.get(
    "https://raw.githubusercontent.com/gilbertbrandow/decoys/main/meta.json"
).json()

EXPECTED_SCHEMA_VERSION = 1
assert meta["schemaVersion"] == EXPECTED_SCHEMA_VERSION, (
    f"Schema version mismatch: expected {EXPECTED_SCHEMA_VERSION}, "
    f"got {meta['schemaVersion']}. Check the decoys repo for breaking changes."
)
```

---

## Tests

```bash
pip install pytest
pytest tests/
```

---

## Data sources

- **Lichess eval dataset**: [database.lichess.org/#evals](https://database.lichess.org/#evals)
- **OTB master games**: [LumbrasGigaBase](https://www.lumbras.com/) or any PGN with ELO headers
- **Published dataset**: see [meta.json](meta.json)
