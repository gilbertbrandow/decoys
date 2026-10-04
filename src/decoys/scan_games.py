"""Scan OTB master game PGN files against the eval DB and emit qualifying decoy positions."""

import json
import shutil
import tempfile
import time
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import chess
import chess.pgn
import py7zr

from decoys.eval_db import lookup, open_db
from decoys.lichess_link import LichessClient, resolve_lichess_url

MOVE_MIN = 20
GM_ELO_THRESHOLD = 2600


def _title_fallback(title: str | None, elo_str: str | None) -> str | None:
    if title:
        return title
    try:
        if elo_str and int(elo_str) >= GM_ELO_THRESHOLD:
            return "GM"
    except (ValueError, TypeError):
        pass
    return None


def _short_fen(board: chess.Board) -> str:
    return " ".join(board.fen().split()[:4])


def _avg_elo(game: chess.pgn.Game) -> int:
    try:
        w = int(game.headers.get("WhiteElo") or 0)
        b = int(game.headers.get("BlackElo") or 0)
        return (w + b) // 2 if w and b else 0
    except ValueError:
        return 0


def _extracted_pgn_path(archive: Path) -> Path:
    return archive.with_suffix(".pgn")


def _ensure_extracted(path: Path) -> Path:
    suffix = path.suffix.lower()
    if suffix not in (".7z", ".zip"):
        return path

    out = _extracted_pgn_path(path)
    if out.exists():
        return out

    print(f"Extracting {path.name} → {out.name} ...")
    if suffix == ".7z":
        with py7zr.SevenZipFile(path, mode="r") as arc:
            pgn_names = [n for n in arc.namelist() if n.lower().endswith(".pgn")]
            if not pgn_names:
                raise ValueError(f"No .pgn file found inside {path}")
            with tempfile.TemporaryDirectory() as tmpdir:
                arc.extractall(path=tmpdir)
                # shutil.move handles cross-device moves (e.g. tmpfs → bind mount in Docker)
                shutil.move(str(Path(tmpdir) / pgn_names[0]), str(out))
    else:
        with zipfile.ZipFile(path) as zf:
            pgn_names = [n for n in zf.namelist() if n.lower().endswith(".pgn")]
            if not pgn_names:
                raise ValueError(f"No .pgn file found inside {path}")
            with tempfile.TemporaryDirectory() as tmpdir:
                zf.extract(pgn_names[0], path=tmpdir)
                shutil.move(str(Path(tmpdir) / pgn_names[0]), str(out))

    print(f"Extracted: {out} ({out.stat().st_size // 1_000_000} MB)")
    return out


def _build_elo_index(pgn_path: Path, min_both_elo: int = 0) -> list[tuple[int, int]]:
    index: list[tuple[int, int]] = []
    with pgn_path.open(encoding="utf-8", errors="replace") as f:
        while True:
            offset = f.tell()
            headers = chess.pgn.read_headers(f)
            if headers is None:
                break
            try:
                w = int(headers.get("WhiteElo") or 0)
                b = int(headers.get("BlackElo") or 0)
            except ValueError:
                continue
            if min_both_elo and (w < min_both_elo or b < min_both_elo):
                continue
            index.append(((w + b) // 2, offset))
    index.sort(key=lambda x: x[0], reverse=True)
    return index


def stream_games(path: Path, min_both_elo: int = 0) -> Iterator[chess.pgn.Game]:
    pgn_path = _ensure_extracted(path)
    with pgn_path.open(encoding="utf-8", errors="replace") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            if min_both_elo:
                try:
                    w = int(game.headers.get("WhiteElo") or 0)
                    b = int(game.headers.get("BlackElo") or 0)
                except ValueError:
                    continue
                if w < min_both_elo or b < min_both_elo:
                    continue
            yield game


def stream_games_by_elo(path: Path, min_both_elo: int = 0) -> Iterator[chess.pgn.Game]:
    pgn_path = _ensure_extracted(path)
    print(f"Building ELO index for {pgn_path.name} ...", flush=True)
    index = _build_elo_index(pgn_path, min_both_elo=min_both_elo)
    print(
        f"Index built: {len(index):,} qualifying games, top avg ELO: {index[0][0] if index else 0}",
        flush=True,
    )
    with pgn_path.open(encoding="utf-8", errors="replace") as f:
        for _avg, offset in index:
            f.seek(offset)
            game = chess.pgn.read_game(f)
            if game is not None:
                yield game


def print_info(path: Path, min_both_elo: int = 0) -> None:
    total = 0
    elos: list[int] = []
    events: Counter[str] = Counter()

    for game in stream_games(path, min_both_elo=min_both_elo):
        total += 1
        avg = _avg_elo(game)
        if avg:
            elos.append(avg)
        events[game.headers.get("Event", "?")] += 1
        if total % 50_000 == 0:
            print(f"  ... {total:,} games scanned so far", flush=True)

    print(f"Total games: {total:,}")
    if elos:
        print(f"Avg ELO range: {min(elos):,} – {max(elos):,}")
    print()
    print("Top 20 events:")
    for event, count in events.most_common(20):
        print(f"  {count:4d}  {event}")


def scan(
    path: Path,
    out_path: Path,
    *,
    db_path: Path,
    min_both_elo: int = 2600,
    sort_by_elo: bool = False,
    event_filter: str | None = None,
    games_limit: int | None = None,
    decoys_limit: int | None = None,
    max_per_game: int = 2,
    fetch_lichess_urls: bool = True,
) -> None:
    start = time.monotonic()
    games_processed = 0
    positions_checked = 0
    decoys_found = 0
    lichess_queries = 0
    seen_fens: set[str] = set()

    conn = open_db(db_path)
    game_source = stream_games_by_elo if sort_by_elo else stream_games

    lichess = LichessClient() if fetch_lichess_urls else None
    lichess_linked = 0

    try:
        with out_path.open("w", encoding="utf-8") as out:
            for game in game_source(path, min_both_elo=min_both_elo):
                event = game.headers.get("Event", "")
                if event_filter and event_filter.lower() not in event.lower():
                    continue

                games_processed += 1
                board = game.board()
                prev_fen_4: str | None = None
                prev_move_uci: str | None = None
                full_game_moves = " ".join(m.uci() for m in game.mainline_moves())
                decoys_this_game = 0
                next_check_at = MOVE_MIN
                game_lichess_url: str | None = None
                game_lichess_fetched = False

                for move_num, node in enumerate(game.mainline(), start=1):
                    move = node.move
                    if move is None:
                        break

                    current_fen_4 = _short_fen(board)

                    if move_num >= next_check_at and prev_fen_4 is not None:
                        positions_checked += 1
                        result = lookup(conn, current_fen_4)
                        if result is not None:
                            next_check_at = move_num + 10

                            if prev_fen_4 in seen_fens:
                                pass
                            else:
                                seen_fens.add(prev_fen_4)
                                decoys_found += 1
                                decoys_this_game += 1

                                if lichess and not game_lichess_fetched:
                                    lichess_queries += 1
                                    print(
                                        f"  [API call #{lichess_queries}] {game.headers.get('White')} vs "
                                        f"{game.headers.get('Black')} — querying Lichess ...",
                                        flush=True,
                                    )
                                    game_lichess_url = resolve_lichess_url(full_game_moves, lichess)
                                    lichess_linked += game_lichess_url is not None
                                    print(f"  → {game_lichess_url}", flush=True)
                                    game_lichess_fetched = True
                                elif lichess and decoys_this_game > 1:
                                    print(
                                        f"  [reuse] {game.headers.get('White')} vs "
                                        f"{game.headers.get('Black')} move {move_num} — reusing {game_lichess_url}",
                                        flush=True,
                                    )

                                record = {
                                    "fen": prev_fen_4,
                                    "opponentMove": prev_move_uci,
                                    "game_moves": full_game_moves,
                                    "bestCp": result["bestCp"],
                                    "depth": result["depth"],
                                    "acceptedMoves": result["acceptedMoves"],
                                    "source": "otb_master",
                                    "event": event,
                                    "date": game.headers.get("Date"),
                                    "white": game.headers.get("White"),
                                    "black": game.headers.get("Black"),
                                    "whiteElo": game.headers.get("WhiteElo"),
                                    "blackElo": game.headers.get("BlackElo"),
                                    "whiteTitle": _title_fallback(
                                        game.headers.get("WhiteTitle"), game.headers.get("WhiteElo")
                                    ),
                                    "blackTitle": _title_fallback(
                                        game.headers.get("BlackTitle"), game.headers.get("BlackElo")
                                    ),
                                    "moveNumber": move_num,
                                    "eco": (game.headers.get("ECO") or "")[:3] or None,
                                    "openingName": game.headers.get("Opening"),
                                    "lichessGameUrl": game_lichess_url,
                                }
                                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                                if decoys_this_game >= max_per_game:
                                    break

                    prev_fen_4 = current_fen_4
                    prev_move_uci = move.uci()
                    board.push(move)

                if games_processed % 1_000 == 0:
                    elapsed = time.monotonic() - start
                    print(
                        f"Games {games_processed:,} | Positions checked {positions_checked:,} | "
                        f"Decoys {decoys_found:,} | Lichess queries {lichess_queries:,} | {elapsed:.0f}s",
                        flush=True,
                    )

                if games_limit and games_processed >= games_limit:
                    break
                if decoys_limit and decoys_found >= decoys_limit:
                    break
    finally:
        conn.close()

    elapsed = time.monotonic() - start
    print(f"Games processed:    {games_processed:,}")
    print(f"Positions checked:  {positions_checked:,}")
    print(f"Decoys found:       {decoys_found:,}  ({decoys_found / max(positions_checked, 1) * 100:.2f}% hit rate)")
    print(f"Lichess queries:    {lichess_queries:,} ({lichess_linked:,} games linked)")
    print(f"Elapsed:            {elapsed:.1f}s")
    print(f"Output:             {out_path}")
