#!/usr/bin/env python3
"""Shared, read-only parsers for the ICRA log-mining scripts."""
from __future__ import annotations
import csv, glob, json, os
from pathlib import Path

DELIVERY_ROOT = Path(__file__).resolve().parents[1]
ROOT = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), DELIVERY_ROOT)
EVAL_ROOT = Path(os.environ.get("NAVILA_EVAL_ROOT", "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"))
BATCH_ROOT = Path(os.environ.get("NAVILA_BATCH_ROOT", "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs"))

RUNS = {
    "L": "pure_baseline_highsuccess100ep_chronological_first50_20260818",
    "OH": "pure_oracle_hint_highsuccess100ep_20260811",
    "OHA": "pure_oracle_hint_action_highsuccess100ep_20260812",
    "FO": "pure_oracle_hint_action_stopgate_highsuccess100ep_20260813",
    "ON": "policy_v2_active50_replay_on_highsuccess100ep_20260816",
    "GEO": "path_following_geometry_m50_20260910",
}
TSVS = {
    "L": ROOT / "final_data2/pure_baseline_highsuccess100ep_chronological_first50_20260818_matched50_full_results.tsv",
    "OH": ROOT / "final_data2/pure_oracle_hint_highsuccess100ep_20260811_matched50_full_results.tsv",
    "OHA": ROOT / "final_data2/pure_oracle_hint_action_highsuccess100ep_20260812_matched50_full_results.tsv",
    "FO": ROOT / "final_data2/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_matched50_full_results.tsv",
    "ON": ROOT / "final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv",
    "GEO": ROOT.parent / "navila_path_following_geometry_m50_20260906/recovery/path_following_geometry_m50_20260910/summary.recovered.tsv",
}

def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def truth(v): return str(v).strip().lower() == "true"

def cohort_ids(): return [r["episode_id"] for r in read_tsv(TSVS["ON"])]

def epidx_by_id(): return {r["episode_id"]: r["episode_idx"] for r in read_tsv(TSVS["ON"])}

def result_dir(run, episode_idx):
    matches = glob.glob(str(EVAL_ROOT / f"*_{run}_ep{episode_idx}"))
    if not matches: return None
    # Exact suffix makes duplicates unlikely; use newest if recovery copies exist.
    return Path(max(matches, key=os.path.getmtime))

def trajectory_path(run, episode_idx):
    d = result_dir(run, episode_idx)
    if not d: return None
    fs = list((d / "trajectories").glob("*.jsonl"))
    return fs[0] if fs else None

def measurement_path(run, episode_idx):
    d = result_dir(run, episode_idx)
    if not d: return None
    fs = list((d / "measurements").glob("*.json"))
    return fs[0] if fs else None

def iter_jsonl(path):
    if not path: return
    with open(path, encoding="utf-8") as f:
        for line in f:
            try: yield json.loads(line)
            except json.JSONDecodeError: continue

def query_rows(run, episode_idx, phase="return"):
    return [r for r in iter_jsonl(trajectory_path(run, episode_idx))
            if r.get("phase") == phase and r.get("step") == r.get("last_vlm_step")]

def write_csv(path, rows, fields=None):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fields is None:
        fields=[]
        for row in rows:
            for key in row:
                if key not in fields: fields.append(key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
