"""Build-time only: fetch the files listed in a SHA-256 manifest from the Hugging Face hub, at a pinned revision.

The Dockerfile checks the result with `sha256sum -c` right after: a file that is not the one in the manifest fails the
build. Nothing of this runs in the pod.

    fetch_weights.py REPO REVISION MANIFEST --local-dir DIR     # plain tree
    fetch_weights.py REPO REVISION MANIFEST --cache-dir DIR     # hub cache layout, as read by hf_hub_download offline
"""

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("revision")
    parser.add_argument("manifest", type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--local-dir", type=Path)
    target.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()

    paths = [line.split(maxsplit=1)[1].strip() for line in args.manifest.read_text().splitlines() if line.strip()]
    for path in paths:
        hf_hub_download(args.repo, path, revision=args.revision, local_dir=args.local_dir, cache_dir=args.cache_dir)
    if args.cache_dir:
        # The library asks for the default revision ("main") without naming a commit: offline, that is this file.
        refs = args.cache_dir / f"models--{args.repo.replace('/', '--')}" / "refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "main").write_text(args.revision)
    print(f"{len(paths)} file(s) fetched from {args.repo}@{args.revision}")


if __name__ == "__main__":
    main()
