import csv, json, glob, statistics as st

RUN_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_highsuccess100ep_20260811"
SUMMARY = f"{RUN_DIR}/summary.tsv"

rows = []
with open(SUMMARY) as f:
    r = csv.DictReader(f, delimiter="\t")
    for row in r:
        rows.append(row)
print(f"total rows: {len(rows)}")

outbound_success = [r for r in rows if r["outbound_success"] == "True"]
print(f"outbound_success: {len(outbound_success)}")
return_fail = [r for r in outbound_success if r["return_success"] == "False"]
print(f"return_success==False among outbound_success: {len(return_fail)}")

records = []
for row in return_fail:
    mfile = row["measurement_file"]
    try:
        with open(mfile) as f:
            m = json.load(f)
    except FileNotFoundError:
        print(f"  MISSING measurement file for ep{row['episode_idx']}: {mfile}")
        continue
    rt = m["round_trip"]
    d_e = rt.get("distance_to_start")  # final distance to start at episode end
    round_trip_success = rt.get("round_trip_success")
    return_success = rt.get("return_success")
    outbound_success = rt.get("outbound_success")
    traj_file = rt.get("trajectory_file")
    # find trajectory jsonl to compute min distance_to_start_m during return phase
    d_min = None
    if traj_file:
        try:
            with open(traj_file) as tf:
                dmins = []
                for line in tf:
                    step = json.loads(line)
                    if step.get("phase") == "return":
                        v = step.get("distance_to_start_m")
                        if v is not None:
                            dmins.append(v)
                if dmins:
                    d_min = min(dmins)
        except FileNotFoundError:
            pass
    records.append({
        "episode_idx": row["episode_idx"], "episode_id": row.get("episode_id",""),
        "d_e": d_e, "d_min": d_min, "round_trip_success": round_trip_success,
        "outbound_stop_distance_to_goal": rt.get("outbound_stop_distance_to_goal"),
    })

print(f"\nrecords with valid measurement: {len(records)}")

d_es = [r["d_e"] for r in records if r["d_e"] is not None]
print(f"\nd_e (final distance to start) stats, n={len(d_es)}:")
print(f"  median={st.median(d_es):.3f}  q1={sorted(d_es)[len(d_es)//4]:.3f}  q3={sorted(d_es)[3*len(d_es)//4]:.3f}  min={min(d_es):.3f}  max={max(d_es):.3f}")
n_gt5 = sum(1 for v in d_es if v > 5)
n_gt10 = sum(1 for v in d_es if v > 10)
print(f"  d_e>5m: {n_gt5}/{len(d_es)} ({100*n_gt5/len(d_es):.1f}%)")
print(f"  d_e>10m: {n_gt10}/{len(d_es)} ({100*n_gt10/len(d_es):.1f}%)")

top5 = sorted(records, key=lambda r: -(r["d_e"] or 0))[:5]
print("\nTop 5 largest d_e:")
for r in top5:
    print(f"  ep{r['episode_idx']} (id={r['episode_id']}) d_e={r['d_e']:.3f}")

d_mins = [r["d_min"] for r in records if r["d_min"] is not None]
print(f"\nd_min_e (min dist to start during return) stats, n={len(d_mins)} (missing: {len(records)-len(d_mins)}):")
if d_mins:
    print(f"  median={st.median(d_mins):.3f}  q1={sorted(d_mins)[len(d_mins)//4]:.3f}  q3={sorted(d_mins)[3*len(d_mins)//4]:.3f}  min={min(d_mins):.3f}  max={max(d_mins):.3f}")
entered = [r for r in records if r["d_min"] is not None and r["d_min"] <= 3.0]
never = [r for r in records if r["d_min"] is not None and r["d_min"] > 3.0]
print(f"\nd_min<=3.0 (entered success zone but left): {len(entered)}")
print(f"d_min>3.0 (never approached): {len(never)}")
if entered:
    print(f"  entered-group d_e median: {st.median([r['d_e'] for r in entered]):.3f}")
    print(f"  entered-group episode_ids: {[r['episode_id'] for r in entered]}")
if never:
    print(f"  never-group d_e median: {st.median([r['d_e'] for r in never]):.3f}")
    print(f"  never-group episode_ids (first 20): {[r['episode_id'] for r in never][:20]}")

# the "2 episodes ended inside success zone but still judged failure"
inside_but_failed = [r for r in records if r["d_e"] is not None and r["d_e"] <= 3.0]
print(f"\nEnded d_e<=3.0m but round_trip judged failure (should be ~2 per checklist): {len(inside_but_failed)}")
for r in inside_but_failed:
    print(f"  ep{r['episode_idx']} id={r['episode_id']} d_e={r['d_e']:.3f} round_trip_success={r['round_trip_success']} outbound_stop_dist={r['outbound_stop_distance_to_goal']}")

with open("/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/analysis/b2_failure_magnitude.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["episode_idx","episode_id","d_e","d_min","round_trip_success","outbound_stop_distance_to_goal"])
    w.writeheader()
    for r in records:
        w.writerow(r)
print("\nsaved: b2_failure_magnitude.csv")
