"""Link source games to their Lichess Masters game, verified by exact move equality.

A `lichessGameUrl` identifies the source game itself, not merely a game that passes
through the puzzle position. A candidate ID is only accepted when the Lichess game's
full move list equals the source game's moves; otherwise the URL is null.
"""

import io
import os
import time
from collections import defaultdict
from collections.abc import Iterable

import chess
import chess.pgn
import requests

EXPLORER_URL = "https://explorer.lichess.org/masters"
PGN_URL = "https://explorer.lichess.org/masters/pgn/{}"
LICHESS_GAME_BASE = "https://lichess.org/{}"
RATE_INTERVAL = 1.0
MAX_CANDIDATES = 15


class LichessClient:
    """Rate-limited Masters Explorer client.

    Retries transient errors (network, 5xx, 429). The position endpoint requires a
    Lichess API token (env `LICHESS_TOKEN`); the PGN endpoint works without one.
    """

    def __init__(self, token: str | None = None, max_attempts: int = 8) -> None:
        self.http = requests.Session()
        token = token or os.environ.get("LICHESS_TOKEN")
        if token:
            self.http.headers["Authorization"] = f"Bearer {token}"
        self.max_attempts = max_attempts
        self._last_req = 0.0

    def _get(self, url: str, params: dict | None = None, *, accept: str) -> requests.Response | None:
        """GET with rate limiting and retries. Returns the 200 or 404 response, or None on failure."""
        backoff = 2.0
        attempts = 0
        while attempts < self.max_attempts:
            elapsed = time.monotonic() - self._last_req
            if elapsed < RATE_INTERVAL:
                time.sleep(RATE_INTERVAL - elapsed)
            try:
                resp = self.http.get(url, params=params, headers={"Accept": accept}, timeout=15)
                self._last_req = time.monotonic()

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    print(f"  429 rate limited — sleeping {retry_after}s", flush=True)
                    time.sleep(retry_after)
                    self._last_req = time.monotonic()
                    continue  # 429 doesn't count as an attempt
                if resp.status_code in (200, 404):
                    return resp
                if resp.status_code == 401:
                    raise RuntimeError(f"401 from {url} — set LICHESS_TOKEN to a valid Lichess API token")

                print(f"  Unexpected status {resp.status_code} — retrying in {backoff:.0f}s", flush=True)

            except requests.RequestException as exc:
                print(f"  Lichess request error ({exc}) — retrying in {backoff:.0f}s", flush=True)

            attempts += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
        return None

    def candidate_ids(self, fen: str) -> list[str] | None:
        """IDs of master games passing through `fen`, or None if the lookup failed."""
        resp = self._get(
            EXPLORER_URL,
            {"fen": fen, "topGames": str(MAX_CANDIDATES), "moves": "0"},
            accept="application/json",
        )
        if resp is None or resp.status_code != 200:
            return None
        return [g["id"] for g in resp.json().get("topGames", [])]

    def game_moves(self, game_id: str) -> str | None:
        """Space-separated UCI moves of a Lichess Masters game, or None if unavailable."""
        resp = self._get(PGN_URL.format(game_id), accept="application/x-chess-pgn")
        if resp is None or resp.status_code != 200:
            return None
        return pgn_to_uci(resp.text)


def pgn_to_uci(pgn_text: str) -> str | None:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None or game.errors:
        return None
    moves = " ".join(m.uci() for m in game.mainline_moves())
    return moves or None


def final_fen(game_moves: str) -> str:
    board = chess.Board()
    for uci in game_moves.split():
        board.push_uci(uci)
    return " ".join(board.fen().split()[:4])


def game_id_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[1]


def resolve_lichess_url(game_moves: str, client: LichessClient) -> str | None:
    """Lichess URL of exactly this game, or None if no candidate has identical moves.

    Queries the game's final position, which few or no other master games reach,
    then verifies each candidate's full move list.
    """
    ids = client.candidate_ids(final_fen(game_moves))
    for game_id in ids or []:
        if client.game_moves(game_id) == game_moves:
            return LICHESS_GAME_BASE.format(game_id)
    return None


def find_link_violations(records: Iterable[dict]) -> dict[str, int]:
    """Lichess URLs shared by records with different `game_moves` → number of distinct games."""
    games_by_url: dict[str, set[str]] = defaultdict(set)
    for r in records:
        url = r.get("lichessGameUrl")
        if url:
            games_by_url[url].add(r["game_moves"])
    return {url: len(games) for url, games in games_by_url.items() if len(games) > 1}
