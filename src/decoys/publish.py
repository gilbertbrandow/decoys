"""Upload decoy_positions.jsonl to a HuggingFace dataset repo."""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from huggingface_hub import HfApi, login
    from huggingface_hub.errors import RepositoryNotFoundError
except ImportError:
    sys.exit(
        "huggingface_hub is required for publishing.\n"
        "Install it with: pip install -r requirements-publish.txt"
    )

REPO_ID = "simongilbertbrandow/chess-decoy-positions"
REPO_TYPE = "dataset"


def check_dataset(path: Path) -> None:
    """Refuse to publish if any lichessGameUrl is shared by different games."""
    from decoys.lichess_link import find_link_violations

    with path.open(encoding="utf-8") as f:
        violations = find_link_violations(json.loads(line) for line in f)
    if violations:
        sample = ", ".join(f"{url} ({n} games)" for url, n in list(violations.items())[:5])
        sys.exit(f"{len(violations)} lichessGameUrl(s) shared by different games, e.g. {sample}")


def main() -> None:
    p = argparse.ArgumentParser(description="Publish decoy_positions.jsonl to HuggingFace")
    p.add_argument("--file", required=True, type=Path, help="Path to decoy_positions.jsonl")
    p.add_argument("--repo", default=REPO_ID, help=f"HuggingFace dataset repo ID (default: {REPO_ID})")
    args = p.parse_args()

    if not args.file.exists():
        sys.exit(f"File not found: {args.file}")
    check_dataset(args.file)

    login(token=os.environ.get("HF_TOKEN"))

    api = HfApi()

    try:
        api.repo_info(repo_id=args.repo, repo_type=REPO_TYPE)
    except RepositoryNotFoundError:
        print(f"Creating dataset repo {args.repo} ...")
        api.create_repo(repo_id=args.repo, repo_type=REPO_TYPE, private=False)

    size_mb = args.file.stat().st_size // 1_000_000
    print(f"Uploading {args.file} ({size_mb} MB) → {args.repo} ...")
    api.upload_file(
        path_or_fileobj=str(args.file),
        path_in_repo="decoy_positions.jsonl",
        repo_id=args.repo,
        repo_type=REPO_TYPE,
        commit_message=f"Update decoy positions ({size_mb} MB)",
    )
    print(f"Done. https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
