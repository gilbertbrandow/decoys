"""One-time repair of `lichessGameUrl` in an existing decoy_positions.jsonl (issue #7).

Earlier scans stamped each game with the top Masters Explorer hit for one of its
positions, which is often a different, higher-rated game. For every source game this:

  1. keeps the existing URL only if that Lichess game's moves equal `game_moves`;
  2. otherwise (or if there was none) re-resolves it with the verified lookup
     used by the scanner (`--no-relink` to skip);
  3. sets it to null if nothing matches.

Lookups are cached in a JSON file so an interrupted run can be resumed.
Re-resolving needs LICHESS_TOKEN; verifying existing URLs does not.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from lichess_link import (
    LICHESS_GAME_BASE,
    LichessClient,
    final_fen,
    find_link_violations,
    game_id_from_url,
)


class CachedClient:
    """LichessClient wrapper that persists every lookup to a JSON file."""

    def __init__(self, client: LichessClient, path: Path) -> None:
        self.client = client
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.pgn: dict[str, str | None] = data.get("pgn", {})
        self.candidates: dict[str, list[str]] = data.get("candidates", {})
        self._dirty = 0

    def _touch(self) -> None:
        self._dirty += 1
        if self._dirty >= 25:
            self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pgn": self.pgn, "candidates": self.candidates}))
        tmp.replace(self.path)
        self._dirty = 0

    def game_moves(self, game_id: str) -> str | None:
        if game_id not in self.pgn:
            self.pgn[game_id] = self.client.game_moves(game_id)
            self._touch()
        return self.pgn[game_id]

    def candidate_ids(self, fen: str) -> list[str] | None:
        if fen not in self.candidates:
            ids = self.client.candidate_ids(fen)
            if ids is None:
                return None  # failed lookup: don't cache, retry on next run
            self.candidates[fen] = ids
            self._touch()
        return self.candidates[fen]


def main() -> None:
    p = argparse.ArgumentParser(description="Repair lichessGameUrl in decoy_positions.jsonl (issue #7)")
    p.add_argument("--in", dest="src", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--cache", type=Path, default=Path("data/lichess_link_cache.json"))
    p.add_argument("--no-relink", action="store_true", help="Only verify existing URLs; never look up new ones")
    args = p.parse_args()

    records = [json.loads(line) for line in args.src.open(encoding="utf-8")]
    client = CachedClient(LichessClient(), args.cache)

    old_url_by_game: dict[str, set[str]] = {}
    for r in records:
        urls = old_url_by_game.setdefault(r["game_moves"], set())
        if r.get("lichessGameUrl"):
            urls.add(r["lichessGameUrl"])

    new_url_by_game: dict[str, str | None] = {}
    outcome: Counter[str] = Counter()
    try:
        for i, (moves, old_urls) in enumerate(old_url_by_game.items(), 1):
            url = next(
                (u for u in sorted(old_urls) if client.game_moves(game_id_from_url(u)) == moves),
                None,
            )
            if url is None and not args.no_relink:
                ids = client.candidate_ids(final_fen(moves)) or []
                game_id = next((g for g in ids if client.game_moves(g) == moves), None)
                url = LICHESS_GAME_BASE.format(game_id) if game_id else None
            if old_urls:
                outcome["kept" if url in old_urls else "replaced" if url else "removed"] += 1
            else:
                outcome["newly linked" if url else "still unlinked"] += 1
            new_url_by_game[moves] = url
            if i % 100 == 0:
                print(f"  {i:,}/{len(old_url_by_game):,} games | {dict(outcome)}", flush=True)
    finally:
        client.save()

    for r in records:
        r["lichessGameUrl"] = new_url_by_game[r["game_moves"]]

    violations = find_link_violations(records)
    if violations:
        sys.exit(f"Invariant violated after healing: {violations}")

    with args.out.open("w", encoding="utf-8") as out:
        for r in records:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    linked_before = sum(1 for g in old_url_by_game.values() if g)
    linked_after = sum(1 for u in new_url_by_game.values() if u)
    print(f"Games:            {len(old_url_by_game):,}")
    for k, v in outcome.items():
        print(f"  {k + ':':<26}{v:,}")
    print(f"Games linked:     {linked_before:,} → {linked_after:,}")
    print(
        f"Records linked:   {sum(1 for r in records if r['lichessGameUrl']):,} / {len(records):,}"
    )
    print(f"Output:           {args.out}")


if __name__ == "__main__":
    main()
