# ── Configuration ────────────────────────────────────────────────────────────
# Required for publish: huggingface-cli login  OR  export HF_TOKEN=hf_xxxx
# Required for Lichess game links in scan-games: export LICHESS_TOKEN=lip_xxxx
#
# Override data dir:  make docker-scan-games DATA_DIR=/my/data
# Override HF repo:   make docker-publish HF_REPO=myuser/my-repo

DATA_DIR   ?= /data
IMAGE      := decoy-producer
HF_REPO    ?= simongilbertbrandow/chess-decoy-positions

EVALS_SRC  := $(DATA_DIR)/raw/lichess_db_eval.jsonl.zst
SQLITE_OUT := $(DATA_DIR)/decoy_evals.sqlite
GAMES_SRC  := $(DATA_DIR)/raw/LumbrasGigaBase_OTB_ELITE_ELO2400.7z
DECOYS_OUT := $(DATA_DIR)/decoy_positions.jsonl

# Resolve data/ relative to this Makefile regardless of where make is invoked
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
HOST_DATA    := $(abspath $(MAKEFILE_DIR)/data)

.PHONY: all build-evals scan-games publish \
        docker-build docker-build-evals docker-scan-games docker-publish docker-all

# ── Local targets (container, or a virtualenv with `pip install -e .`) ────────

all: build-evals scan-games

build-evals:
	python -m decoys.build_evals --src $(EVALS_SRC) --out $(SQLITE_OUT)

scan-games:
	python -m decoys.run_scan \
	  --games $(GAMES_SRC) \
	  --db    $(SQLITE_OUT) \
	  --out   $(DECOYS_OUT) \
	  --sort-by-elo \
	  --min-both-elo 2600

publish:
	python -m decoys.publish --file $(DECOYS_OUT) --repo $(HF_REPO)

# ── Docker targets ────────────────────────────────────────────────────────────

docker-build:
	docker build -t $(IMAGE) .

docker-build-evals: docker-build
	docker run --rm \
	  -v $(HOST_DATA):/data \
	  $(IMAGE) make build-evals

docker-scan-games: docker-build
	docker run --rm \
	  -v $(HOST_DATA):/data \
	  -e LICHESS_TOKEN=$(LICHESS_TOKEN) \
	  $(IMAGE) make scan-games

docker-publish: docker-build
	docker run --rm \
	  -v $(HOST_DATA):/data \
	  -v $(HOME)/.cache/huggingface:/root/.cache/huggingface:ro \
	  -e HF_TOKEN=$(HF_TOKEN) \
	  -e HF_REPO=$(HF_REPO) \
	  $(IMAGE) make publish HF_REPO=$(HF_REPO)

docker-all: docker-build
	docker run --rm \
	  -v $(HOST_DATA):/data \
	  -v $(HOME)/.cache/huggingface:/root/.cache/huggingface:ro \
	  -e HF_TOKEN=$(HF_TOKEN) \
	  -e LICHESS_TOKEN=$(LICHESS_TOKEN) \
	  $(IMAGE) make all HF_REPO=$(HF_REPO)
