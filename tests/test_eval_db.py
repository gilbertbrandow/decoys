import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_db import (
    CLUSTER_CP,
    MAX_ABS_CP,
    MAX_ACCEPTED,
    MIN_ACCEPTED,
    MIN_DEPTH,
    MIN_DROPOFF_CP,
    classify,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FEN_WHITE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"       # starting position, white to move
FEN_BLACK = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"  # after 1.e4, black to move


def _make_eval(pvs: list[dict], depth: int = MIN_DEPTH + 2) -> list[dict]:
    return [{"depth": depth, "pvs": pvs}]


def _qualifying_pvs(best_cp: int = 40) -> list[dict]:
    """3 moves in cluster, 1 move outside with >MIN_DROPOFF_CP drop."""
    return [
        {"cp": best_cp,      "line": "e2e4 e7e5"},
        {"cp": best_cp - 15, "line": "d2d4 d7d5"},
        {"cp": best_cp - 25, "line": "g1f3 g8f6"},
        {"cp": best_cp - (MIN_DROPOFF_CP + 10), "line": "f2f4 e7e5"},
    ]


# ── Happy path ────────────────────────────────────────────────────────────────

def test_classify_returns_result_for_qualifying_position():
    result = classify(_make_eval(_qualifying_pvs(40)), FEN_WHITE)
    assert result is not None
    assert result["bestCp"] == 40
    assert result["depth"] == MIN_DEPTH + 2
    assert len(result["acceptedMoves"]) == 3
    assert result["acceptedMoves"][0]["uci"] == "e2e4"
    assert result["acceptedMoves"][0]["dropCp"] == 0


def test_classify_accepted_moves_are_within_cluster():
    result = classify(_make_eval(_qualifying_pvs(50)), FEN_WHITE)
    assert result is not None
    for move in result["acceptedMoves"]:
        assert move["dropCp"] <= CLUSTER_CP


# ── Depth filter ──────────────────────────────────────────────────────────────

def test_classify_returns_none_when_all_evals_below_min_depth():
    evals = [{"depth": MIN_DEPTH - 1, "pvs": _qualifying_pvs()}]
    assert classify(evals, FEN_WHITE) is None


def test_classify_uses_highest_depth_eval_when_multiple_present():
    evals = [
        {"depth": MIN_DEPTH - 1, "pvs": [{"cp": 300, "line": "e2e4 e7e5"}]},
        {"depth": MIN_DEPTH + 5, "pvs": _qualifying_pvs(40)},
    ]
    result = classify(evals, FEN_WHITE)
    assert result is not None
    assert result["bestCp"] == 40


# ── CP range filter ───────────────────────────────────────────────────────────

def test_classify_returns_none_when_best_cp_exceeds_max():
    pvs = _qualifying_pvs(best_cp=MAX_ABS_CP + 1)
    assert classify(_make_eval(pvs), FEN_WHITE) is None


def test_classify_returns_none_when_best_cp_is_too_negative():
    pvs = [
        {"cp": -(MAX_ABS_CP + 1), "line": "e2e4 e7e5"},
        {"cp": -(MAX_ABS_CP + 15), "line": "d2d4 d7d5"},
        {"cp": -(MAX_ABS_CP + 25), "line": "g1f3 g8f6"},
        {"cp": -(MAX_ABS_CP + 60), "line": "f2f4 e7e5"},
    ]
    assert classify(_make_eval(pvs), FEN_WHITE) is None


def test_classify_accepts_position_at_exact_max_abs_cp():
    pvs = _qualifying_pvs(best_cp=MAX_ABS_CP)
    result = classify(_make_eval(pvs), FEN_WHITE)
    assert result is not None


# ── Accepted move count ───────────────────────────────────────────────────────

def test_classify_returns_none_when_too_few_moves_in_cluster():
    pvs = [
        {"cp": 40, "line": "e2e4 e7e5"},
        {"cp": 25, "line": "d2d4 d7d5"},
        # only 2 in cluster — third is outside
        {"cp": 40 - (MIN_DROPOFF_CP + 5), "line": "g1f3 g8f6"},
    ]
    assert classify(_make_eval(pvs), FEN_WHITE) is None


def test_classify_returns_none_when_too_many_moves_in_cluster():
    pvs = [{"cp": 40 - i * 3, "line": f"move{i} reply{i}"} for i in range(MAX_ACCEPTED + 1)]
    pvs.append({"cp": 40 - (MIN_DROPOFF_CP + 10), "line": "last reply"})
    assert classify(_make_eval(pvs), FEN_WHITE) is None


# ── Dropoff filter ────────────────────────────────────────────────────────────

def test_classify_returns_none_when_no_move_outside_cluster():
    pvs = [
        {"cp": 40, "line": "e2e4 e7e5"},
        {"cp": 25, "line": "d2d4 d7d5"},
        {"cp": 15, "line": "g1f3 g8f6"},
        # no 4th move at all — first_outside_idx >= len(unique)
    ]
    assert classify(_make_eval(pvs), FEN_WHITE) is None


def test_classify_returns_none_when_dropoff_below_minimum():
    pvs = [
        {"cp": 40, "line": "e2e4 e7e5"},
        {"cp": 25, "line": "d2d4 d7d5"},
        {"cp": 15, "line": "g1f3 g8f6"},
        {"cp": 40 - (MIN_DROPOFF_CP - 1), "line": "f2f4 e7e5"},  # drop just below threshold
    ]
    assert classify(_make_eval(pvs), FEN_WHITE) is None


def test_classify_accepts_position_at_exact_min_dropoff():
    pvs = [
        {"cp": 40, "line": "e2e4 e7e5"},
        {"cp": 25, "line": "d2d4 d7d5"},
        {"cp": 15, "line": "g1f3 g8f6"},
        {"cp": 40 - MIN_DROPOFF_CP, "line": "f2f4 e7e5"},
    ]
    result = classify(_make_eval(pvs), FEN_WHITE)
    assert result is not None


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_classify_deduplicates_pvs_with_same_first_move():
    pvs = [
        {"cp": 40, "line": "e2e4 e7e5"},
        {"cp": 38, "line": "e2e4 c7c5"},   # same first move as above — skipped
        {"cp": 25, "line": "d2d4 d7d5"},
        {"cp": 15, "line": "g1f3 g8f6"},
        {"cp": -15, "line": "f2f4 e7e5"},
    ]
    result = classify(_make_eval(pvs), FEN_WHITE)
    assert result is not None
    ucis = [m["uci"] for m in result["acceptedMoves"]]
    assert len(ucis) == len(set(ucis)), "duplicate UCIs in accepted moves"


def test_classify_skips_pvs_with_empty_line():
    pvs = [
        {"cp": 40, "line": ""},             # no first move — skipped
        {"cp": 38, "line": "e2e4 e7e5"},
        {"cp": 25, "line": "d2d4 d7d5"},
        {"cp": 15, "line": "g1f3 g8f6"},
        {"cp": -15, "line": "f2f4 e7e5"},
    ]
    result = classify(_make_eval(pvs), FEN_WHITE)
    assert result is not None
    assert all(m["uci"] != "" for m in result["acceptedMoves"])


# ── CP normalisation (side to move) ──────────────────────────────────────────

def test_classify_normalises_cp_for_black_to_move():
    # Engine reports from white's perspective; negate for black-to-move positions.
    # cp=-40 means good for black; normalized to +40.
    pvs = [
        {"cp": -40, "line": "e7e5 e2e4"},
        {"cp": -25, "line": "d7d5 d2d4"},
        {"cp": -15, "line": "g8f6 g1f3"},
        {"cp": 15,  "line": "f7f5 e2e4"},   # normalized: -15, drop from best: 55
    ]
    result = classify(_make_eval(pvs), FEN_BLACK)
    assert result is not None
    assert result["bestCp"] == 40


def test_classify_returns_none_for_pvs_without_cp_field():
    pvs = [
        {"mate": 3, "line": "e2e4 e7e5"},
        {"mate": 2, "line": "d2d4 d7d5"},
        {"mate": 1, "line": "g1f3 g8f6"},
    ]
    assert classify(_make_eval(pvs), FEN_WHITE) is None
