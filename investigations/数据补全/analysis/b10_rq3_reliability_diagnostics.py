import csv, glob, json, os, re, statistics as st
from collections import defaultdict, Counter

RUN_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816"
MATCHED50 = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv"
EVAL_RESULTS_ROOT = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"

BEARING_THRESHOLD = 0.90

arbiter_re = re.compile(r"\[hint_arbiter\] step=(\d+) override=(\w+) reason=(\S+)")
stopgate_re = re.compile(r"\[stop_gate\] step=(\d+) decision=(\w+) d=([\-\d.]+) conf=([\-\d.]+)")
return_start_re = re.compile(r"\[return\] start step=(\d+)")

matched50 = list(csv.DictReader(open(MATCHED50), delimiter="\t"))
summary_rows = {r["episode_idx"]: r for r in csv.DictReader(open(f"{RUN_DIR}/summary.tsv"), delimiter="\t")}

per_ep_out = []
parse_notes = []

# pooled accumulators
pooled_reason_counts = Counter()
pooled_bearing_conf_values_all = []          # confidence at every return decision step
pooled_bearing_conf_values_withheld = []      # confidence at withheld steps only
pooled_stopgate_states = Counter()            # accepted/vetoed/deferred/forced/pass over ALL return steps w/ a stop_gate decision line
pooled_anchor_promo_total = 0
pooled_anchor_promo_withheld = 0
pooled_routehint_total = 0
pooled_routehint_withheld = 0
pooled_hintaction_v11_total = 0
pooled_hintaction_v11_withheld = 0
pooled_deferred_low_conf = [0]
pooled_deferred_high_conf = [0]

def load_traj_return_records(traj_path):
    """step -> record, phase=='return' only."""
    out = {}
    with open(traj_path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("phase") != "return":
                continue
            out[d["step"]] = d
    return out


for row in matched50:
    idx = row["episode_idx"]
    exit_code = row["exit_code"]
    outbound_success = row["outbound_success"]
    return_success = row["return_success"]
    round_trip_success = row["round_trip_success"]

    srow = summary_rows.get(idx)
    ep_rec = dict(
        episode_idx=idx, episode_id=row["episode_id"], exit_code=exit_code,
        outbound_success=outbound_success, return_success=return_success,
        round_trip_success=round_trip_success,
        in_cohort=False, parse_failure=None,
    )

    if exit_code != "0":
        ep_rec["parse_failure"] = f"exit_code={exit_code}"
        per_ep_out.append(ep_rec)
        parse_notes.append(f"ep{idx}: excluded, exit_code={exit_code}")
        continue

    if outbound_success != "True":
        ep_rec["parse_failure"] = "outbound_success=False, not in Return-phase cohort"
        per_ep_out.append(ep_rec)
        continue

    ep_rec["in_cohort"] = True

    if not srow:
        ep_rec["parse_failure"] = "no summary.tsv row"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: no summary row"); continue

    eval_log = srow["eval_log"]
    measurement_file = srow["measurement_file"]

    if not os.path.exists(eval_log):
        ep_rec["parse_failure"] = f"missing eval_log {eval_log}"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: missing eval_log"); continue

    text = open(eval_log, errors="replace").read()
    lines = text.splitlines()

    m = return_start_re.search(text)
    return_start_step = int(m.group(1)) if m else None
    if return_start_step is None:
        ep_rec["parse_failure"] = "no [return] start line found"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: no return-start marker"); continue

    arbiter_events = []  # (step, override_bool, reason_str)
    for ln in lines:
        am = arbiter_re.search(ln)
        if am:
            step = int(am.group(1))
            if step < return_start_step:
                continue
            arbiter_events.append((step, am.group(2) == "True", am.group(3)))

    stopgate_events = []  # (step, decision, conf)
    for ln in lines:
        sm = stopgate_re.search(ln)
        if sm:
            step = int(sm.group(1))
            if step < return_start_step:
                continue
            stopgate_events.append((step, sm.group(2), float(sm.group(4))))

    # measurement -> trajectory path
    if not os.path.exists(measurement_file):
        ep_rec["parse_failure"] = "missing measurement_file"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: missing measurement_file"); continue
    try:
        mjson = json.load(open(measurement_file))
    except json.JSONDecodeError as e:
        ep_rec["parse_failure"] = f"measurement JSON corrupt: {e}"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: measurement JSON corrupt ({e})"); continue

    rt = mjson.get("round_trip", {})
    traj_rel = rt.get("trajectory_file")
    ep_dir = os.path.dirname(os.path.dirname(measurement_file))
    traj_path = os.path.join(ep_dir, traj_rel) if traj_rel else None
    if not traj_path or not os.path.exists(traj_path):
        ep_rec["parse_failure"] = "missing trajectory file"
        per_ep_out.append(ep_rec); parse_notes.append(f"ep{idx}: missing trajectory file"); continue

    traj = load_traj_return_records(traj_path)

    # ---- Table A: r_bearing (confidence at each arbiter decision step) ----
    bearing_conf = []
    bearing_withheld = 0
    bearing_missing = 0
    for step, override, reason in arbiter_events:
        rec = traj.get(step)
        conf = None
        if rec and rec.get("hint_action_arbiter"):
            conf = rec["hint_action_arbiter"].get("relocalization_confidence")
        if conf is None and rec and rec.get("route_memory"):
            conf = rec["route_memory"].get("relocalization_confidence")
        if conf is None:
            bearing_missing += 1
            continue
        bearing_conf.append(conf)
        pooled_bearing_conf_values_all.append(conf)
        if conf < BEARING_THRESHOLD:
            bearing_withheld += 1
            pooled_bearing_conf_values_withheld.append(conf)

    n_decisions = len(arbiter_events)

    # ---- Table B: reason-code breakdown ----
    reason_counts = Counter(r for _, _, r in arbiter_events)
    for r, c in reason_counts.items():
        pooled_reason_counts[r] += c

    override_true = sum(1 for _, ov, _ in arbiter_events if ov)
    override_rate = override_true / n_decisions if n_decisions else None

    # ---- Table C: stop_gate state distribution (return phase) ----
    sg_counts = Counter(d for _, d, _ in stopgate_events)
    for d, c in sg_counts.items():
        pooled_stopgate_states[d] += c
    r_distance_withheld = sg_counts.get("deferred", 0)
    n_stopgate_decisions = sum(c for k, c in sg_counts.items() if k != "pass")
    deferred_low_conf = sum(1 for _, d, c in stopgate_events if d == "deferred" and c < 0.5)
    deferred_high_conf = sum(1 for _, d, c in stopgate_events if d == "deferred" and c >= 0.5)
    pooled_deferred_low_conf[0] += deferred_low_conf
    pooled_deferred_high_conf[0] += deferred_high_conf

    # ---- r_pose: reliability_v11_consumer_v2.jsonl (anchor_promotion / route_hint) ----
    v11_path = os.path.join(ep_dir, "reliability_v11_consumer_v2.jsonl")
    anchor_promo_total = anchor_promo_withheld = 0
    routehint_total = routehint_withheld = 0
    hintaction_v11_blocked = sum(1 for _, _, r in arbiter_events if r.startswith("v11_consumer_v2_blocked"))
    if os.path.exists(v11_path):
        for ln in open(v11_path, errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if d.get("event") != "v11_consumer_v2_decision":
                continue
            step = d.get("step")
            if step is None or step < return_start_step:
                continue
            op = d.get("operation")
            allow = d.get("executed_allow")
            if op == "anchor_promotion":
                anchor_promo_total += 1
                if allow is False:
                    anchor_promo_withheld += 1
            elif op == "route_hint":
                routehint_total += 1
                if allow is False:
                    routehint_withheld += 1
    else:
        parse_notes.append(f"ep{idx}: no reliability_v11_consumer_v2.jsonl found")

    pooled_anchor_promo_total += anchor_promo_total
    pooled_anchor_promo_withheld += anchor_promo_withheld
    pooled_routehint_total += routehint_total
    pooled_routehint_withheld += routehint_withheld
    pooled_hintaction_v11_total += n_decisions
    pooled_hintaction_v11_withheld += hintaction_v11_blocked

    # ---- terminal state at final return step ----
    if traj:
        last_step = max(traj.keys())
        last_rec = traj[last_step]
        last_sg = (last_rec.get("stop_gate") or {}).get("gate_decision")
        last_vlm_out = (last_rec.get("last_vlm_output") or "")
        vlm_said_stop = "i think i should stop" in last_vlm_out.lower()
        if last_sg == "forced":
            term_class = "forced_no_vlm_stop"
        elif last_sg in ("accepted", "deferred") and vlm_said_stop:
            term_class = "vlm_stop_accepted"
        elif last_sg == "vetoed":
            term_class = "ended_after_veto_or_timeout"
        else:
            term_class = "timeout_or_other"
    else:
        last_sg = None
        term_class = "no_return_trajectory_records"

    ep_rec.update(
        return_start_step=return_start_step,
        n_return_decision_steps=n_decisions,
        n_bearing_conf_missing=bearing_missing,
        r_bearing_withheld=bearing_withheld,
        r_bearing_withheld_pct=(100 * bearing_withheld / n_decisions) if n_decisions else None,
        r_bearing_conf_median=(st.median(bearing_conf) if bearing_conf else None),
        r_bearing_conf_in_085_090=sum(1 for c in bearing_conf if 0.85 <= c < 0.90),
        reason_vlm_action_consistent=reason_counts.get("vlm_action_consistent", 0),
        reason_occupied_in_local_map_path=reason_counts.get("occupied_in_local_map_path", 0),
        reason_vlm_conflicts_with_clear_hint=reason_counts.get("vlm_conflicts_with_clear_hint", 0),
        reason_target_too_close=reason_counts.get("target_too_close", 0),
        reason_low_relocalization_confidence=reason_counts.get("low_relocalization_confidence", 0),
        reason_v11_consumer_v2_blocked=hintaction_v11_blocked,
        override_true=override_true,
        override_rate=override_rate,
        n_stop_gate_decision_steps=n_stopgate_decisions,
        stop_gate_accepted=sg_counts.get("accepted", 0),
        stop_gate_vetoed=sg_counts.get("vetoed", 0),
        stop_gate_deferred=sg_counts.get("deferred", 0),
        stop_gate_forced=sg_counts.get("forced", 0),
        stop_gate_pass=sg_counts.get("pass", 0),
        r_distance_withheld_pct=(100 * r_distance_withheld / n_stopgate_decisions) if n_stopgate_decisions else None,
        deferred_low_conf=deferred_low_conf,
        deferred_high_conf=deferred_high_conf,
        anchor_promotion_total=anchor_promo_total,
        anchor_promotion_withheld=anchor_promo_withheld,
        route_hint_v11_total=routehint_total,
        route_hint_v11_withheld=routehint_withheld,
        final_stop_gate_decision=last_sg,
        terminal_classification=term_class,
    )
    per_ep_out.append(ep_rec)

# ---------------- write TSV ----------------
fieldnames = [
    "episode_idx", "episode_id", "exit_code", "outbound_success", "return_success",
    "round_trip_success", "in_cohort", "parse_failure", "return_start_step",
    "n_return_decision_steps", "n_bearing_conf_missing",
    "r_bearing_withheld", "r_bearing_withheld_pct", "r_bearing_conf_median",
    "r_bearing_conf_in_085_090",
    "reason_vlm_action_consistent", "reason_occupied_in_local_map_path",
    "reason_vlm_conflicts_with_clear_hint", "reason_target_too_close",
    "reason_low_relocalization_confidence", "reason_v11_consumer_v2_blocked",
    "override_true", "override_rate",
    "n_stop_gate_decision_steps", "stop_gate_accepted", "stop_gate_vetoed",
    "stop_gate_deferred", "stop_gate_forced", "stop_gate_pass",
    "r_distance_withheld_pct", "deferred_low_conf", "deferred_high_conf",
    "anchor_promotion_total", "anchor_promotion_withheld",
    "route_hint_v11_total", "route_hint_v11_withheld",
    "final_stop_gate_decision", "terminal_classification",
]

OUT_TSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policy_v2_reliability_diagnostics_20260819.tsv")
with open(OUT_TSV, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    for r in per_ep_out:
        w.writerow(r)

print(f"Wrote {OUT_TSV} ({len(per_ep_out)} rows)")

# ---------------- pooled summary ----------------
cohort = [r for r in per_ep_out if r.get("in_cohort")]
parsed = [r for r in cohort if r.get("n_return_decision_steps") is not None]
print(f"\nmatched50 rows: {len(matched50)}")
print(f"cohort (outbound_success & exit_code==0): {len(cohort)}")
print(f"fully parsed (have decision-step data): {len(parsed)}")
print(f"cohort but not fully parsed: {len(cohort) - len(parsed)}")
for r in cohort:
    if r.get("n_return_decision_steps") is None:
        print(f"  ep{r['episode_idx']}: {r.get('parse_failure')}")

total_decisions = sum(r["n_return_decision_steps"] for r in parsed)
print(f"\nTotal Return-phase arbiter decision steps (pooled): {total_decisions}")
print(f"Total bearing-confidence-missing steps: {sum(r['n_bearing_conf_missing'] for r in parsed)}")

total_bearing_withheld = sum(r["r_bearing_withheld"] for r in parsed)
print(f"\n=== r_bearing ===")
print(f"pooled withheld: {total_bearing_withheld}/{total_decisions} = {100*total_bearing_withheld/total_decisions:.2f}%")
per_ep_bearing_pct = [r["r_bearing_withheld_pct"] for r in parsed if r["r_bearing_withheld_pct"] is not None]
print(f"per-episode withheld%% median={st.median(per_ep_bearing_pct):.2f} "
      f"Q1={sorted(per_ep_bearing_pct)[len(per_ep_bearing_pct)//4]:.2f} "
      f"Q3={sorted(per_ep_bearing_pct)[3*len(per_ep_bearing_pct)//4]:.2f}")
print(f"pooled confidence value distribution: n={len(pooled_bearing_conf_values_all)} "
      f"median={st.median(pooled_bearing_conf_values_all):.4f}")
frac_in_band = sum(1 for c in pooled_bearing_conf_values_withheld if 0.85 <= c < 0.90)
print(f"of withheld steps, fraction with conf in [0.85,0.90): {frac_in_band}/{len(pooled_bearing_conf_values_withheld)} "
      f"= {100*frac_in_band/len(pooled_bearing_conf_values_withheld):.2f}%")

print(f"\n=== Table B reason codes (pooled, n={total_decisions}) ===")
for k, v in pooled_reason_counts.most_common():
    print(f"  {k}: {v} ({100*v/total_decisions:.2f}%)")

total_override = sum(r["override_true"] for r in parsed)
print(f"\noverride=True total: {total_override} ({100*total_override/total_decisions:.2f}% of decisions)")
per_ep_override_rate = [r["override_rate"] for r in parsed if r["override_rate"] is not None]
print(f"per-episode override rate: median={st.median(per_ep_override_rate):.4f} mean={st.mean(per_ep_override_rate):.4f}")

print(f"\n=== r_distance (stop_gate) pooled state counts over Return phase (all decision-producing steps incl. pass) ===")
for k, v in pooled_stopgate_states.most_common():
    print(f"  {k}: {v}")
non_pass_total = sum(c for k, c in pooled_stopgate_states.items() if k != "pass")
print(f"non-pass total: {non_pass_total}")
print(f"deferred (withheld) share of non-pass: {100*pooled_stopgate_states['deferred']/non_pass_total:.2f}%")
dlc, dhc = pooled_deferred_low_conf[0], pooled_deferred_high_conf[0]
print(f"of deferred steps: conf<0.5(min_confidence)={dlc}, conf>=0.5={dhc} "
      f"(r_in==r_out==3.0 in this run -> geometric-hysteresis branch is unreachable, "
      f"so every deferred step is attributable to either low raw confidence or the "
      f"distance_authority_low_reliability flag, though that flag itself is not separately logged)")

print(f"\n=== r_pose (v11 consumer) ===")
print(f"anchor_promotion: {pooled_anchor_promo_withheld}/{pooled_anchor_promo_total} withheld "
      f"({100*pooled_anchor_promo_withheld/pooled_anchor_promo_total:.2f}%)" if pooled_anchor_promo_total else "anchor_promotion: no events logged")
print(f"route_hint (v11 layer): {pooled_routehint_withheld}/{pooled_routehint_total} withheld "
      f"({100*pooled_routehint_withheld/pooled_routehint_total:.2f}%)" if pooled_routehint_total else "route_hint: no events logged")
print(f"hint_action_override blocked by v11 (visible in arbiter reason): {pooled_hintaction_v11_withheld}/{pooled_hintaction_v11_total} "
      f"= {100*pooled_hintaction_v11_withheld/pooled_hintaction_v11_total:.2f}% of ALL Return decision steps")

print(f"\n=== terminal classification ===")
term_counts = Counter(r.get("terminal_classification") for r in parsed)
for k, v in term_counts.most_common():
    print(f"  {k}: {v}")

print(f"\n=== parse notes ===")
for n in parse_notes:
    print(f"  {n}")
