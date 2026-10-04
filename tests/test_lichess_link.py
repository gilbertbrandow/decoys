from decoys.lichess_link import final_fen, find_link_violations, pgn_to_uci, resolve_lichess_url

# ── Fixtures ──────────────────────────────────────────────────────────────────

GAME_A = "e2e4 e7e5 g1f3 b8c6 f1b5"
GAME_B = "e2e4 e7e5 g1f3 b8c6 f1c4"  # shares the first four plies with GAME_A


class FakeClient:
    def __init__(self, candidates: list[str] | None, moves_by_id: dict[str, str | None]) -> None:
        self.candidates = candidates
        self.moves_by_id = moves_by_id
        self.queried_fens: list[str] = []

    def candidate_ids(self, fen: str) -> list[str] | None:
        self.queried_fens.append(fen)
        return self.candidates

    def game_moves(self, game_id: str) -> str | None:
        return self.moves_by_id.get(game_id)


def _rec(moves: str, url: str | None) -> dict:
    return {"game_moves": moves, "lichessGameUrl": url}


# ── resolve_lichess_url ───────────────────────────────────────────────────────


def test_resolve_accepts_only_identical_game() -> None:
    client = FakeClient(["other", "mine"], {"other": GAME_B, "mine": GAME_A})
    assert resolve_lichess_url(GAME_A, client) == "https://lichess.org/mine"


def test_resolve_rejects_top_game_that_only_shares_a_position() -> None:
    client = FakeClient(["other"], {"other": GAME_B})
    assert resolve_lichess_url(GAME_A, client) is None


def test_resolve_rejects_same_game_with_different_continuation() -> None:
    client = FakeClient(["longer"], {"longer": GAME_A + " a7a6"})
    assert resolve_lichess_url(GAME_A, client) is None


def test_resolve_none_when_lookup_fails() -> None:
    assert resolve_lichess_url(GAME_A, FakeClient(None, {})) is None


def test_resolve_queries_final_position() -> None:
    client = FakeClient([], {})
    resolve_lichess_url(GAME_A, client)
    assert client.queried_fens == ["r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq -"]


# ── helpers ───────────────────────────────────────────────────────────────────


def test_final_fen_has_four_fields() -> None:
    assert final_fen("e2e4") == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"


def test_pgn_to_uci() -> None:
    pgn = '[Event "x"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0\n'
    assert pgn_to_uci(pgn) == GAME_A


def test_pgn_to_uci_rejects_illegal_moves() -> None:
    assert pgn_to_uci('[Event "x"]\n\n1. e4 e5 2. Ke3 1-0\n') is None


# ── find_link_violations (pre-publish invariant) ─────────────────────────────


def test_no_violation_for_one_game_with_several_records() -> None:
    records = [_rec(GAME_A, "https://lichess.org/a"), _rec(GAME_A, "https://lichess.org/a")]
    assert find_link_violations(records) == {}


def test_violation_when_url_shared_by_different_games() -> None:
    records = [_rec(GAME_A, "https://lichess.org/a"), _rec(GAME_B, "https://lichess.org/a")]
    assert find_link_violations(records) == {"https://lichess.org/a": 2}


def test_null_urls_are_ignored() -> None:
    assert find_link_violations([_rec(GAME_A, None), _rec(GAME_B, None)]) == {}
