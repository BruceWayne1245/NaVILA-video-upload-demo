import sys
sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/2026-07-28-promotion-quarantine-controller-model/code")
import extract_dwell_dataset as ed
import glob, os, csv
from collections import Counter

ed.BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
ed.OUT_CSV = "/tmp/claude-1006/-home-teambruce/c26c1924-d639-4a9c-b712-10d36d74d793/scratchpad/dwell_dataset_reliable30v3.csv"

pattern = f"{ed.BASE}/*promotion_shadow_reliable30v3_20260731_ep*"
ep_dirs = sorted(d for d in glob.glob(pattern) if os.path.isdir(d))
print(f"{len(ep_dirs)} reliable30v3 episode dirs found")
for d in ep_dirs:
    print(" ", os.path.basename(d))

all_rows = []
n_ok, n_empty, n_err = 0, 0, 0
for d in ep_dirs:
    try:
        rows = ed.process_episode(d)
        if rows:
            all_rows.extend(rows)
            n_ok += 1
        else:
            n_empty += 1
            print(f"  EMPTY: {os.path.basename(d)}")
    except Exception as e:
        n_err += 1
        print(f"  ERR: {os.path.basename(d)}: {e}")

print(f"episodes ok={n_ok} empty={n_empty} err={n_err}")
print(f"total rows={len(all_rows)}")
if all_rows:
    fieldnames = sorted(set().union(*[r.keys() for r in all_rows]))
    with open(ed.OUT_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"wrote {ed.OUT_CSV}")
    print("label distribution:", Counter(r['label'] for r in all_rows))
