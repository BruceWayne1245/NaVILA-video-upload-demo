import json, math, csv, glob, os, re, sys
from deep_analysis import load_traj, build_outbound_curve, pos_for_distance
from deep_analysis2 import body_frame_bearing_distance, wrap180

EVAL = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
TAGS = [
    "canonical_report_next_stopgate_100ep_20260720",
    "canonical_report_next_stopgate_50ep_20260719",
    "shadow_hint_swap_50ep_20260714",
]

def episode_paths(tag):
    out=[]
    for d in sorted(glob.glob(f"{EVAL}/*{tag}*_ep*")):
        ep=re.search(r"_ep(\d+)$", d).group(1)
        mfiles=glob.glob(os.path.join(d,"measurements","*.json"))
        if not mfiles: continue
        mfiles.sort(key=lambda p:int(re.search(r"(\d+)\.json$",p).group(1)))
        step=int(re.search(r"(\d+)\.json$",mfiles[-1]).group(1))
        t=os.path.join(d,"trajectories",f"output_{step}.jsonl")
        if os.path.exists(t): out.append((tag,ep,mfiles[-1],t))
    return out

FEATS = ["overlap_ratio","corridor_degeneracy_ratio","icp_near_tie_basin_count","icp_basin_count",
    "icp_best_to_second_score_ratio","icp_best_to_second_rotation_delta_deg","icp_best_to_second_translation_delta_m",
    "confidence","inlier_count","mean_residual_m","median_residual_m","anchor_points","current_points",
    "anchor_z_span_m","current_z_span_m","estimated_distance_to_anchor_m"]

def num(v):
    try: return float(v)
    except: return ""

def loc_feats(r):
    loc=r.get("localizability")
    mn=mx=""
    if isinstance(loc,dict):
        ev=loc.get("eigenvalues")
        if isinstance(ev,list) and ev:
            vals=[float(x) for x in ev if isinstance(x,(int,float))]
            if vals: mn=min(vals); mx=max(vals)
    cond = (mn/mx) if (mn!="" and mx not in ("",0)) else ""
    return mn, cond

def main(out_csv):
    eps=[]
    for tag in TAGS: eps.extend(episode_paths(tag))
    print(f"episodes to process: {len(eps)}", flush=True)
    cols=(["tag","episode","anchor_index","attempt","true_dist","ang_err","dist_err","label_bad_bearing"]
          + FEATS + ["loc_min_eig","loc_cond","match_class","icp_ambiguity"])
    n_rows=0
    with open(out_csv,"w",newline="") as f:
        w=csv.writer(f); w.writerow(cols)
        for i,(tag,ep,m,t) in enumerate(eps):
            try:
                rt=json.load(open(m))["round_trip"]
            except Exception:
                continue
            recs=rt.get("route_relocalization_diagnostics",{}).get("covisibility_records")
            if not recs: continue
            try:
                traj=load_traj(t); curve=build_outbound_curve(traj)
            except Exception:
                continue
            tby={r["step"]:r for r in traj}
            ret=[r["step"] for r in traj if r.get("phase")=="return"]
            if not ret: continue
            ret0=min(ret)
            adist={r["anchor_index"]:r["anchor_distance_from_start_m"] for r in recs}
            apos={idx:pos_for_distance(curve,d) for idx,d in adist.items()}
            for r in recs:
                idx=r["anchor_index"]
                if idx not in apos: continue
                step=ret0+(r["attempt"]-1)*5
                tr=tby.get(step)
                if not tr: continue
                rx,ry,ryaw=tr["position"][0],tr["position"][1],tr["yaw_rad"]
                tx,ty=apos[idx]
                tb,td=body_frame_bearing_distance(rx,ry,ryaw,tx,ty)
                ang=abs(wrap180(r.get("estimated_bearing_to_anchor_deg",0)-tb))
                de=abs(r.get("estimated_distance_to_anchor_m",0)-td)
                lab=1 if ang>30 else 0
                mn,cond=loc_feats(r)
                row=[tag,ep,idx,r["attempt"],round(td,3),round(ang,2),round(de,3),lab]
                row+=[num(r.get(k)) for k in FEATS]
                row+=[mn,cond,r.get("match_class") or "", r.get("icp_ambiguity") or ""]
                w.writerow(row); n_rows+=1
            if (i+1)%20==0: print(f"  ...{i+1}/{len(eps)} episodes, {n_rows} rows", flush=True)
    print(f"DONE: {n_rows} rows -> {out_csv}", flush=True)

if __name__=="__main__":
    main("/home/teambruce/scratch_inv/an/icp_dataset.csv")
