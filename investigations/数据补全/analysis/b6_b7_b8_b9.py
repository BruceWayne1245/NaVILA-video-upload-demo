import csv, json, os, glob, re, statistics as st

def load_summary(run_dir):
    rows = list(csv.DictReader(open(f"{run_dir}/summary.tsv"), delimiter="\t"))
    return rows

def arrival_success_deficit(run_dir, label):
    rows = load_summary(run_dir)
    outbound_success = [r for r in rows if r["outbound_success"] == "True"]
    n_ob = len(outbound_success)
    arrivals = 0
    successes = 0
    for r in outbound_success:
        mfile = r["measurement_file"]
        if not mfile or not os.path.exists(mfile):
            continue
        try:
            m = json.load(open(mfile))
        except json.JSONDecodeError:
            continue
        rt = m["round_trip"]
        d_e = rt.get("distance_to_start")
        rts = rt.get("round_trip_success")
        traj_rel = rt.get("trajectory_file")
        ep_dir = os.path.dirname(os.path.dirname(mfile))
        d_min = None
        if traj_rel:
            tp = os.path.join(ep_dir, traj_rel)
            if os.path.exists(tp):
                dmins = [json.loads(l).get("distance_to_start_m") for l in open(tp) if json.loads(l).get("phase")=="return" and json.loads(l).get("distance_to_start_m") is not None]
                if dmins: d_min = min(dmins)
        entered = (d_min is not None and d_min <= 3.0) or (d_e is not None and d_e <= 3.0)
        if entered: arrivals += 1
        if rts: successes += 1
    deficit = arrivals - successes
    print(f"\n{label}: outbound_success(n)={n_ob}  arrival={arrivals} ({100*arrivals/n_ob:.2f}%)  success={successes} ({100*successes/n_ob:.2f}%)  deficit={deficit} ({100*deficit/n_ob:.2f}pt)")
    return dict(n_ob=n_ob, arrivals=arrivals, successes=successes, deficit=deficit)

print("=== B6: arrival / success / termination-deficit ===")
r1 = arrival_success_deficit("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_highsuccess100ep_20260811", "oracle_hint")
r2 = arrival_success_deficit("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812", "oracle_hint_action")
r3 = arrival_success_deficit("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_stopgate_highsuccess100ep_20260813", "oracle_hint_action_stop")

print(f"\noracle_hint_action_stop vs oracle_hint_action: success +{r3['successes']-r2['successes']}pts(count), arrival +{r3['arrivals']-r2['arrivals']}, deficit change {r3['deficit']-r2['deficit']}")

print("\n=== B7: arbiter coverage recompute (oracle_hint_action) ===")
RUN = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812"
arbiter_re = re.compile(r"\[hint_arbiter\] step=(\d+) override=(\w+) reason=(\S+)")
per_ep = {}
reason_counts = {}
for logf in sorted(glob.glob(f"{RUN}/ep*_eval.log")):
    ep = re.search(r"ep(\d+)_eval\.log", logf).group(1)
    n=0; nov=0; reasons={}
    for line in open(logf, errors="replace"):
        m = arbiter_re.search(line)
        if m:
            n+=1
            reasons[m.group(3)] = reasons.get(m.group(3),0)+1
            reason_counts[m.group(3)] = reason_counts.get(m.group(3),0)+1
            if m.group(2)=="True": nov+=1
    if n>0:
        per_ep[ep] = dict(total=n, overrides=nov, coverage=nov/n)

total_decisions = sum(v["total"] for v in per_ep.values())
total_overrides = sum(v["overrides"] for v in per_ep.values())
print(f"episodes with >=1 decision: {len(per_ep)}")
print(f"total decisions: {total_decisions}  total overrides: {total_overrides}  overall rate: {100*total_overrides/total_decisions:.2f}%")
print(f"reason code counts: {reason_counts}")
for k,v in reason_counts.items():
    print(f"  {k}: {v} ({100*v/total_decisions:.2f}%)")
covs = [v["coverage"] for v in per_ep.values()]
print(f"per-episode coverage: median={st.median(covs):.4f} mean={st.mean(covs):.4f}")
n_covered = sum(1 for v in per_ep.values() if v["overrides"]>0)
print(f"episodes with >=1 override: {n_covered}/{len(per_ep)}")
avg_decisions = st.mean([v["total"] for v in per_ep.values()])
print(f"avg decision steps per episode: {avg_decisions:.2f}")

# group by return success/fail
summ_rows = load_summary(RUN)
ep_return = {r["episode_idx"]: r["return_success"] for r in summ_rows}
succ_covs = [v["coverage"] for ep,v in per_ep.items() if ep_return.get(ep)=="True"]
fail_covs = [v["coverage"] for ep,v in per_ep.items() if ep_return.get(ep)=="False"]
print(f"\nreturn_success group: n={len(succ_covs)} median_cov={st.median(succ_covs) if succ_covs else None:.4f} mean={st.mean(succ_covs) if succ_covs else None:.4f}")
print(f"return_fail group: n={len(fail_covs)} median_cov={st.median(fail_covs) if fail_covs else None:.4f} mean={st.mean(fail_covs) if fail_covs else None:.4f}")

print("\n=== B8: canonical-100 cross-validation ===")
RUN2 = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_100ep_20260812"
per_ep2 = {}
reason_counts2 = {}
for logf in sorted(glob.glob(f"{RUN2}/ep*_eval.log")):
    ep = re.search(r"ep(\d+)_eval\.log", logf).group(1)
    n=0; nov=0
    for line in open(logf, errors="replace"):
        m = arbiter_re.search(line)
        if m:
            n+=1
            reason_counts2[m.group(3)] = reason_counts2.get(m.group(3),0)+1
            if m.group(2)=="True": nov+=1
    if n>0: per_ep2[ep] = dict(total=n, overrides=nov)
td2 = sum(v["total"] for v in per_ep2.values())
to2 = sum(v["overrides"] for v in per_ep2.values())
print(f"episodes with decisions: {len(per_ep2)}  total decisions: {td2}  overrides: {to2}  rate: {100*to2/td2:.2f}%")
print(f"reason codes: {reason_counts2}")

ids_hs = set(r["episode_idx"] for r in load_summary("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812"))
ids_canon = set(r["episode_idx"] for r in load_summary(RUN2))
print(f"\nepisode_idx overlap between high-success-100 and canonical-100 (same manifest indices, NOTE: episode_idx isn't a stable cross-manifest key by itself, this is just index overlap): {len(ids_hs & ids_canon)}/{len(ids_hs)}")
