# decoys

A pipeline for generating chess decoy puzzles from OTB master games and Lichess engine evaluations.

A **decoy puzzle** is a position where there are several equally-good continuations, there is no "only move". The position might be better or worse for the playing side.

The purpose is for these to be trained alongside normal tactics, in order to nullify the fact that the user otherwise knows they are looking for a single winning move.

The output is a JSONL file (`decoy_positions.jsonl`). The schema is versioned and documented in [`schema.json`](schema.json). The canonical published dataset and its download URL are described in [`meta.json`](meta.json).

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
pip install -r requirements.txt -e .

python -m decoys.build_evals \
  --src data/raw/lichess_db_eval.jsonl.zst \
  --out data/decoy_evals.sqlite

python -m decoys.run_scan \
  --games data/raw/LumbrasGigaBase_OTB_ELITE_ELO2400.7z \
  --db    data/decoy_evals.sqlite \
  --out   data/decoy_positions.jsonl \
  --sort-by-elo \
  --min-both-elo 2600
```

---

## Configuration

| Flag | Default | Description |
| --- | --- | --- |
| `--min-both-elo` | 2600 | Minimum ELO for both players |
| `--sort-by-elo` | off | Process highest-rated games first |
| `--max-per-game` | 2 | Max decoy positions to emit per game |
| `--decoys-limit` | none | Stop after N decoys found |
| `--no-lichess-urls` | off | Skip Lichess game URL lookup (faster; no token needed) |
| `--event-filter` | none | Only include games whose Event header matches |

---

## Schema

Each line of `decoy_positions.jsonl` is a JSON object. The full schema is in [`schema.json`](schema.json).

---

## Schema versioning

`meta.json` contains the current `schemaVersion`. Consumers should check this before importing to detect breaking changes:

```python
import requests, json

meta = requests.get("https://raw.githubusercontent.com/gilbertbrandow/decoys/main/meta.json").json()

EXPECTED_SCHEMA_VERSION = 1
assert meta["schemaVersion"] == EXPECTED_SCHEMA_VERSION, (
    f"Schema version mismatch: expected {EXPECTED_SCHEMA_VERSION}, "
    f"got {meta['schemaVersion']}. Check the decoys repo for breaking changes."
)
```

---

## Tests and checks

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install # dev dependencies + this package (editable)
make check   # ruff + mypy + pytest, same as CI
```

CI (`.github/workflows/ci.yml`) runs the same `make` targets on every push to `main` and on pull requests. VS Code picks up `.venv` automatically via `.vscode/settings.json`.

---

## Data sources

- Lichess eval dataset: [database.lichess.org/#evals](https://database.lichess.org/#evals)
- OTB master games: [LumbrasGigaBase](https://www.lumbras.com/)
- Published dataset: see [meta.json](meta.json)
