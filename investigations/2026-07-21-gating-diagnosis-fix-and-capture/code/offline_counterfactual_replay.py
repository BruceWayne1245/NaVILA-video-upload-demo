import json, math, csv, statistics
import deep_analysis
from paths import build_paths
from deep_analysis import load_traj, build_outbound_curve, pos_for_distance
from deep_analysis2 import body_frame_bearing_distance, wrap180

# ---- 1. z-stats + threshold from the labeled dataset (Phase-1 dataclass fields only) ----
FEATS = ["inlier_count","icp_best_to_second_score_ratio","icp_near_tie_basin_count","confidence"]
vals = {f:[] for f in FEATS}; rows=[]
with open("icp_dataset.csv") as fh:
    for r in csv.DictReader(fh):
        rec={}
        ok=True
        for f in FEATS:
            try: rec[f]=float(r[f])
            except: ok=False; break
        if not ok: continue
        rec["label"]=int(r["label_bad_bearing"])
        for f in FEATS: vals[f].append(rec[f])
        rows.append(rec)
stats={f:(statistics.mean(vals[f]), statistics.pstdev(vals[f]) or 1.0) for f in FEATS}

def unreliability(rec):
    """higher = more likely a BAD reading. Phase-1 hand combo, dataclass fields only."""
    def z(f,v): m,s=stats[f]; return (v-m)/s
    inl = rec.get("inlier_count"); ratio=rec.get("icp_best_to_second_score_ratio")
    nt = rec.get("icp_near_tie_basin_count"); conf=rec.get("confidence")
    if None in (inl,ratio,nt,conf): return None
    return (-z("inlier_count",inl) + z("icp_best_to_second_score_ratio",ratio)
            + z("icp_near_tie_basin_count",nt) - z("confidence",conf))

# calibrate threshold: pick U so that among predicted-bad, precision ~= 0.75
scored=[(unreliability(r), r["label"]) for r in rows]
scored=[(u,l) for u,l in scored if u is not None]
scored.sort(reverse=True)  # highest U first
def precision_at(thr):
    pb=[l for u,l in scored if u>=thr]
    return (sum(pb)/len(pb) if pb else 0, len(pb))
# sweep to find precision ~0.75 and also report AUC-ish coverage
import numpy as np
us=np.array([u for u,_ in scored]); ls=np.array([l for _,l in scored])
THR=None
for q in np.linspace(0.95,0.30,40):
    t=np.quantile(us,q); p,n=precision_at(t)
    if p<=0.75:
        THR=t; break
if THR is None: THR=np.quantile(us,0.5)
p_at,n_at=precision_at(THR)
recall_at = sum(1 for u,l in scored if u>=THR and l==1)/max(1,sum(ls))
print(f"z-stats 就绪. 选定阈值 U>={THR:.2f}: 判坏精度={p_at*100:.0f}%, 覆盖真坏={recall_at*100:.0f}% (判坏{n_at}条)")
print(f"(即: 一条读数 U>={THR:.2f} 就当作'低可信/退化', 注入C会对它 defer-not-veto / 降权)\n")

# ================= PART 1: d类 (到家却失败) 注入C回放 =================
DCLASS = {5:"veto",20:"veto",498:"veto",680:"veto",89:"nostop",382:"nostop",537:"nostop",889:"nostop"}
Pd = build_paths(list(DCLASS))
print("="*80)
print("PART 1 — 注入C(低可信就别否决/降权停止) 对 8 个 d 类的反事实回放")
print(f"{'ep':>5} {'类型':>6} {'到家最近':>7} | {'停止尝试':>7} {'半径内停止尝试':>12} | {'该刻current可信度':>16} | 判定")
rec_c=0
for ep,typ in DCLASS.items():
    m,t=Pd[str(ep)]; rt=json.load(open(m))["round_trip"]
    traj=load_traj(t); tby={r["step"]:r for r in traj}; curve=build_outbound_curve(traj)
    start=traj[0]["position"][:2]
    recs=rt["route_relocalization_diagnostics"]["covisibility_records"]
    ret0=min(r["step"] for r in traj if r.get("phase")=="return")
    by_att={}
    for r in recs: by_att.setdefault(r["attempt"],[]).append(r)
    pe=rt["phase_events"]
    # stop attempts (return, vlm issued stop)
    stops=[e["step"] for e in pe if e.get("event")=="vlm_command" and e.get("phase")=="return" and "stop" in str(e.get("output","")).lower()]
    def true_dist(step):
        p=tby.get(step);
        return math.hypot(p["position"][0]-start[0],p["position"][1]-start[1]) if p else None
    # for veto type: within-radius stop attempts + reliability of that attempt's reading
    within=[]
    for s in stops:
        d=true_dist(s)
        if d is None or d>=3.0: continue
        att=round((s-ret0)/5)+1
        pair=by_att.get(att,[])
        # unreliability of the WORST-reliability (most-degenerate) reading that attempt (proxy for the poisoned authority)
        us_=[unreliability(r) for r in pair]; us_=[u for u in us_ if u is not None]
        within.append((s,d,max(us_) if us_ else None))
    mind=min([true_dist(r["step"]) for r in traj if r.get("phase")=="return" and true_dist(r["step"]) is not None])
    if typ=="veto":
        flagged=[w for w in within if w[2] is not None and w[2]>=THR]
        recovered = len(flagged)>0
        rc = f"✅救回 (半径内有{len(flagged)}次停止的读数被判低可信→放行)" if recovered else "❌未救 (半径内停止读数看着'可信'=自信地错,漏网)"
        if recovered: rec_c+=1
        maxu = max([w[2] for w in within if w[2] is not None], default=None)
        maxu_s = "NA" if maxu is None else f"{maxu:.2f}"
        print(f"{ep:>5} {typ:>6} {mind:>6.2f}m | {len(stops):>7} {len(within):>12} | U_max={maxu_s:>7} | {rc}")
    else:
        print(f"{ep:>5} {typ:>6} {mind:>6.2f}m | {len(stops):>7} {'—':>12} | {'—':>16} | ⚠️VLM没发停止, 注入C无从放行→需'到家强制停止'(不在C范围)")
print(f"\n注入C 可救回(veto型): {rec_c}/4;  nostop型4个需另加'高置信到家强制停止'机制")

# ================= PART 2: 13卡死集 注入A/B可行性 =================
PIN = {5:11,20:8,319:4,367:11,498:5,500:10,669:4,680:6,813:6,889:9,994:6,1038:4,653:10}
Pp = build_paths(list(PIN))
print("\n"+"="*80)
print("PART 2 — 注入A/B: pin以下(到家那段)锚点是否可靠? (决定current能否跟着走回家)")
print(f"{'ep':>5} {'pin':>4} | {'pin以下锚点数':>11} {'其中可靠(近距准确)':>16} | 判定")
recoverable=0
for ep,pin in PIN.items():
    m,t=Pp[str(ep)]; rt=json.load(open(m))["round_trip"]
    traj=load_traj(t); tby={r["step"]:r for r in traj}; curve=build_outbound_curve(traj)
    recs=rt["route_relocalization_diagnostics"]["covisibility_records"]
    ret0=min(r["step"] for r in traj if r.get("phase")=="return")
    adist={r["anchor_index"]:r["anchor_distance_from_start_m"] for r in recs}
    apos={i:pos_for_distance(curve,d) for i,d in adist.items()}
    # for anchors below pin: gather readings, find robot's closest approach, check true accuracy + unreliability there
    below=[i for i in adist if i<pin]
    good=0; considered=0
    for idx in below:
        rs=[r for r in recs if r["anchor_index"]==idx]
        if len(rs)<3: continue
        # closest approach: min true dist
        best=None
        for r in rs:
            att=r["attempt"]; step=ret0+(att-1)*5; tr=tby.get(step)
            if not tr: continue
            tx,ty=apos[idx]; tb,td=body_frame_bearing_distance(tr["position"][0],tr["position"][1],tr["yaw_rad"],tx,ty)
            ang=abs(wrap180(r.get("estimated_bearing_to_anchor_deg",0)-tb))
            if best is None or td<best[0]: best=(td,ang,r)
        if best is None: continue
        considered+=1
        td,ang,r=best
        u=unreliability(r)
        # "reliable escape anchor": robot actually gets near it AND it's accurate there
        if td<1.5 and ang<30: good+=1
    frac = good/considered if considered else 0
    verdict = "✅可跟回家(到家段多数锚点可靠)" if frac>=0.5 and considered>=2 else ("⚠️部分" if good>=1 else "❌到家段也退化→需视觉/建图")
    if frac>=0.5 and considered>=2: recoverable+=1
    print(f"{ep:>5} a{pin:<3} | {len(below):>11} {good}/{considered:>14} | {verdict}")
print(f"\n注入A/B 有望让current跟回家的: {recoverable}/13 (其余到家段本身退化,超出门控可修范围)")
