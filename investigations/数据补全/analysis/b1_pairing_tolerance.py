import gzip, json, csv, statistics as st

DATASET = "/mnt/SSD4T/teambruce/projects/navila-isaac/vlnce_assets/vln_ce_isaac_v1.json.gz"
PAIRS_TSV = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/code/high_outbound_success_100ep_selection.tsv"

with gzip.open(DATASET, "rt", encoding="utf-8") as f:
    data = json.load(f)
episodes = data["episodes"] if isinstance(data, dict) else data
print(f"total episodes in dataset: {len(episodes)}")

pairs = []
with open(PAIRS_TSV) as f:
    r = csv.DictReader(f, delimiter="\t")
    for row in r:
        pairs.append(row)
print(f"pairs in high-success-100 manifest: {len(pairs)}")

results = []
for row in pairs:
    out_idx = int(row["episode_idx"])
    ret_idx = int(row["neighbor_idx"])
    out_ep = episodes[out_idx]
    ret_ep = episodes[ret_idx]
    out_path = [(float(p[0]), float(p[1]), float(p[2])) for p in out_ep["reference_path"]]
    ret_path = [(float(p[0]), float(p[1]), float(p[2])) for p in ret_ep["reference_path"]]
    def d3(a,b):
        return ((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5
    d_start = d3(ret_path[-1], out_path[0])   # ||P_ret[-1] - P_out[0]||
    d_goal = d3(ret_path[0], out_path[-1])    # ||P_ret[0] - P_out[-1]||
    results.append({
        "episode_idx": out_idx, "neighbor_idx": ret_idx,
        "episode_id": row["episode_id"], "neighbor_episode_id": row["neighbor_episode_id"],
        "d_start": d_start, "d_goal": d_goal,
    })

d_starts = [r["d_start"] for r in results]
d_goals = [r["d_goal"] for r in results]

def summarize(vals, name):
    print(f"\n{name}: n={len(vals)}")
    print(f"  mean={statistics_mean(vals):.4f}  std={statistics_std(vals):.4f}  median={st.median(vals):.4f}  min={min(vals):.4f}  max={max(vals):.4f}")

def statistics_mean(v): return sum(v)/len(v)
def statistics_std(v): return st.pstdev(v)

summarize(d_starts, "d_start = ||P_ret[-1] - P_out[0]||")
summarize(d_goals, "d_goal = ||P_ret[0] - P_out[-1]||")

n_gt1 = sum(1 for v in d_starts if v > 1.0)
n_gt2 = sum(1 for v in d_starts if v > 2.0)
print(f"\nd_start > 1.0m: {n_gt1}/{len(d_starts)}")
print(f"d_start > 2.0m: {n_gt2}/{len(d_starts)}")

top5 = sorted(results, key=lambda r: -r["d_start"])[:5]
print("\nTop 5 largest d_start:")
for r in top5:
    print(f"  episode_id={r['episode_id']} (idx={r['episode_idx']}) neighbor_episode_id={r['neighbor_episode_id']} d_start={r['d_start']:.3f}")

# histogram bins
bins = [0,0.25,0.5,0.75,1.0,1.5,2.0,3.0,5.0,999]
hist = [0]*(len(bins)-1)
for v in d_starts:
    for i in range(len(bins)-1):
        if bins[i] <= v < bins[i+1]:
            hist[i] += 1
            break
print("\nd_start histogram:")
for i in range(len(bins)-1):
    print(f"  [{bins[i]},{bins[i+1]}): {hist[i]}")

with open("/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/analysis/b1_pairing_distances.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["episode_idx","neighbor_idx","episode_id","neighbor_episode_id","d_start","d_goal"])
    w.writeheader()
    for r in results:
        w.writerow(r)
print("\nsaved: b1_pairing_distances.csv")
