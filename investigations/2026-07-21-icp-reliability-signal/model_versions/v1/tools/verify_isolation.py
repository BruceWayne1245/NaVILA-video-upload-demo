#!/usr/bin/env python3
"""Fail closed if the frozen source, live source, or directory boundary changed."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
EXPECTED = {
    "route_memory_agent.py": "29915c12b188fe1d2a62cfaf77ee59a1d9c6c80b86896bdf8ef65e085e693005",
    "round_trip_eval.py": "cbf84464cd736db94104e8966b7954eec3ce7088ad48e668b83bf50615aa5e71",
    "stop_gate.py": "654ce2b0f15e30c0caba92e1c4e1467f530e32a307525e9842f6cf76e8bd0c03",
    "hint_action_arbiter.py": "f87323fa4f851b44ea78805b8684e9da5d90a51742cef0c896c9c5b1f6f41a93",
    "relocalization.py": "226a87b68d5727982a03763da19ec10baf7f90f8d61a66f29e288b8e6bfb09c1",
    "cli_args.py": "8cc1f663b2ec87182d36708eee134fef17041c770501b9ca207fb5c0b18835f4",
    "instruction_rewriter.py": "f10e07fcbeaa1482e7df7b4734cc9e8a7e9c0c4e73a4030b9543a07481adff4c",
    "local_map.py": "b51bbf2cff645b0f1ca922f09ba59c0f19825cffae2303e55c700de88b88970d",
    "scan_context.py": "980ce568b31680f52569572c9454b18b0d57860ebebb13177d839ce36b04c3dc",
    "topdown_route_map.py": "fa71b39c9b1cbe5dc71965d545cae206d342e03863c4f6bca398ecaf7a6e7e64",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    errors = []
    symlinks = [
        path for path in ROOT.rglob("*")
        if path.is_symlink() and ".venv" not in path.relative_to(ROOT).parts
    ]
    if symlinks:
        errors.append(f"symbolic links are forbidden: {symlinks}")
    for name, expected in EXPECTED.items():
        frozen = ROOT / "upstream_snapshot" / "scripts" / name
        if not frozen.exists() or digest(frozen) != expected:
            errors.append(f"frozen baseline changed: {frozen}")
        live = LIVE / name
        if not live.exists() or digest(live) != expected:
            errors.append(f"live baseline no longer matches recorded source: {live}")
        candidate = ROOT / "candidate" / "scripts" / name
        if not candidate.exists():
            errors.append(f"candidate copy missing: {candidate}")
        if candidate.exists() and os.path.samefile(candidate, live):
            errors.append(f"candidate aliases live file: {candidate}")
    if errors:
        print("ISOLATION CHECK FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    print("ISOLATION CHECK PASSED")
    print(f"experiment_root={ROOT}")
    print(f"live_source={LIVE}")
    print("symlinks=0; frozen hashes=ok; live hashes=ok; candidate files are distinct inodes")


if __name__ == "__main__":
    main()
