"""
Below-pin anchor registrability along the REAL return trajectory
(2026-07-21 capture re-run, --capture_icp_replay_dataset).

Answers FINDINGS.md §4 step 2a properly: the earlier "1/13 recoverable" number
was computed from LIVE covisibility_records, which -- because of the pin --
contained only the single incidental reading each below-pin anchor happened to
get. This re-does it with the captured raw point clouds: for each below-pin
anchor, we FORCE-match the anchor's own cloud against the return-step clouds
where the robot physically passes closest to it, using the SAME live ICP
(relocalization.sequential_pair_anchor_relocalization), and score vs ground
truth. That tells us whether un-sticking the pin could let `current` walk home
(Route 1) or the home stretch is itself degenerate (vision wall, Route 2).
"""
import os, sys, json, glob, math, argparse
sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
import numpy as np
from relocalization import sequential_pair_anchor_relocalization
from route_memory_agent import RouteAnchor

EVR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
BATCH = "capture_reliability_16ep_20260721_accumulated"

# pin anchor per stuck episode (from data/03; 669 excluded -- VLM-startup fail, no capture)
PIN = {5:11, 20:8, 319:4, 367:11, 498:5, 500:10, 680:6, 813:6, 889:9, 994:6, 1038:4, 653:10}

K_STEPS = 3          # ICP-evaluate the K closest-approach return steps per anchor
STEP_STRIDE_FALLBACK = 5  # when trajectory JSONL is missing, sample step files at this stride for pose lookup
NEAR_M = 1.5         # robot must get this close for registrability to even be in question
BEAR_OK = 30.0       # bearing-error threshold (deg) for "accurate"
DIST_OK = 0.5        # distance-error threshold (m) for "accurate"


def wrap180(a):
    while a > 180: a -= 360
    while a < -180: a += 360
    return a

def pose_yaw(pose):  # pose = [x,y,z, qw,qx,qy,qz]
    q0, q1, q2, q3 = pose[3], pose[4], pose[5], pose[6]
    return math.atan2(2*(q1*q2 + q0*q3), q0**2 + q1**2 - q2**2 - q3**2)

def true_rel(robot_pose, ax, ay):
    """true (distance_m, bearing_deg) from robot body frame to anchor (ax,ay)."""
    rx, ry = robot_pose[0], robot_pose[1]
    yaw = pose_yaw(robot_pose)
    dx, dy = ax - rx, ay - ry
    dist = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dy, dx) - yaw)
    return dist, wrap180(bearing)

def find_capture_dir(ep):
    dd = glob.glob(f"{EVR}/*{BATCH}_ep{ep}")
    if not dd: return None
    d = os.path.join(dd[0], "icp_replay_dataset")
    return d if os.path.isdir(d) else None

def load_anchors(cap_dir, total_len):
    data = json.load(open(os.path.join(cap_dir, "anchors.json")))["anchors"]
    out = {}
    for a in data:
        pts = a.get("local_map_points_xyz_body")
        wp = a.get("world_pose")
        ra = RouteAnchor(
            index=int(a["index"]), pose_from_start=[0.0,0.0,0.0],
            distance_from_start_m=float(a["distance_from_start_m"]),
            route_remaining_to_start_m=float(max(0.0, total_len - a["distance_from_start_m"])),
            descriptor={"local_map_points_body": np.asarray(pts, dtype=np.float32)} if pts else None,
            metadata={"world_pose": wp},
        )
        out[ra.index] = dict(ra=ra, wx=wp[0], wy=wp[1], npts=len(pts) if pts else 0)
    return out

def load_return_traj(ep, cap_dir):
    """Return list of {step, position, world_pose} for the return phase.
    Primary source: the (cheap) trajectory JSONL. Fallback (used when the
    measurement/trajectory output was lost to the intermittent Isaac
    write-corruption bug, e.g. ep498): read robot_world_pose straight out of
    the captured per-step files at a stride -- same pose, same frame as the
    clouds, just more I/O so we subsample."""
    dd = glob.glob(f"{EVR}/*{BATCH}_ep{ep}")
    tfs = sorted(glob.glob(os.path.join(dd[0], "trajectories", "*.jsonl")))
    if tfs:
        recs = [json.loads(l) for l in open(tfs[-1])]
        out = []
        for r in recs:
            if r.get("phase") != "return":
                continue
            wp = list(r["position"][:3]) + list(r["quaternion_wxyz"])
            out.append(dict(step=r["step"], position=r["position"], world_pose=wp))
        return out
    # fallback: strided step files
    files = sorted(os.listdir(os.path.join(cap_dir, "steps")))
    out = []
    for fname in files[::STEP_STRIDE_FALLBACK]:
        try:
            d = json.load(open(os.path.join(cap_dir, "steps", fname)))
        except json.JSONDecodeError:
            continue
        wp = d["robot_world_pose"]
        out.append(dict(step=d["step"], position=wp[:3], world_pose=wp))
    return out

def load_step_cloud(cap_dir, step):
    fp = os.path.join(cap_dir, "steps", f"frame_step{step:06d}.json")
    if not os.path.exists(fp): return None
    try:
        d = json.load(open(fp))
    except json.JSONDecodeError:
        return None
    pts = d.get("local_map_points_xyz_body")
    if not pts: return None
    return d["robot_world_pose"], np.asarray(pts, dtype=np.float32)

def icp_match(step_cloud, target_anchor):
    """Force a single-anchor match (next=None) and return its candidate."""
    descriptor = {"local_map_points_body": step_cloud}
    cands = sequential_pair_anchor_relocalization(
        descriptor, target_anchor, None, diagnostics={}, return_candidates=True,
        icp_objective="point_to_point", voxel_size_m=0.10, max_points=512,
        quality_policy="diagnostic",
    )
    if not cands: return None
    for c in cands:
        if c.anchor_index == target_anchor.index:
            return c
    return cands[0]


def analyze_anchor(cap_dir, ret, ainfo):
    """Return per-anchor registrability result, evaluated at K closest steps."""
    ax, ay = ainfo["wx"], ainfo["wy"]
    # closest-approach return steps by true distance
    ds = [(math.hypot(r["position"][0]-ax, r["position"][1]-ay), r["step"]) for r in ret]
    ds.sort()
    closest_d = ds[0][0]
    evals = []
    for d_true_xy, step in ds[:K_STEPS]:
        sc = load_step_cloud(cap_dir, step)
        if sc is None: continue
        rpose, cloud = sc
        cand = icp_match(cloud, ainfo["ra"])
        if cand is None: continue
        tdist, tbear = true_rel(rpose, ax, ay)
        rdist = cand.distance_to_anchor_m
        rbear = cand.bearing_to_anchor_deg
        berr = abs(wrap180(rbear - tbear))
        derr = abs(rdist - tdist)
        evals.append(dict(step=step, approach=math.hypot(rpose[0]-ax, rpose[1]-ay),
                          berr=berr, derr=derr, mc=cand.match_class,
                          nt=cand.near_tie_basin_count, conf=cand.confidence,
                          b2s=cand.best_to_second_score_ratio, inl=cand.inlier_count))
    if not evals:
        return dict(closest_d=closest_d, ok=False, berr=None, derr=None, note="no-cloud")
    # best (most favorable) reading -> gives the pin-unstick hypothesis its best shot
    best = min(evals, key=lambda e: e["berr"])
    registrable = (best["approach"] < NEAR_M and best["berr"] < BEAR_OK and best["derr"] < DIST_OK)
    return dict(closest_d=closest_d, ok=registrable, berr=best["berr"], derr=best["derr"],
                approach=best["approach"], mc=best["mc"], nt=best["nt"], conf=best["conf"],
                b2s=best["b2s"], inl=best["inl"], n_eval=len(evals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, nargs="+", default=sorted(PIN))
    args = ap.parse_args()

    print(f"{'='*92}")
    print("BELOW-PIN ANCHOR REGISTRABILITY (real ICP re-match against 2026-07-21 capture)")
    print(f"registrable = closest approach <{NEAR_M}m AND bearing_err <{BEAR_OK}° AND dist_err <{DIST_OK}m (best of {K_STEPS} closest steps)")
    print(f"{'='*92}\n")

    ep_summary = []
    for ep in args.episodes:
        if ep not in PIN: continue
        pin = PIN[ep]
        cap = find_capture_dir(ep)
        if cap is None:
            print(f"ep{ep}: capture MISSING\n"); continue
        anchors = None
        try:
            adata = json.load(open(os.path.join(cap, "anchors.json")))["anchors"]
            total_len = max(a["distance_from_start_m"] for a in adata)
            anchors = load_anchors(cap, total_len)
        except json.JSONDecodeError:
            print(f"ep{ep}: anchors.json corrupt\n"); continue
        ret = load_return_traj(ep, cap)
        if not ret:
            print(f"ep{ep}: no return poses (trajectory + step fallback both empty)\n"); continue
        below = [i for i in sorted(anchors) if 0 < i < pin and anchors[i]["npts"] > 0]
        print(f"ep{ep}  pin=a{pin}  below-pin anchors: {below}")
        results = {}
        for idx in below:
            r = analyze_anchor(cap, ret, anchors[idx])
            results[idx] = r
            tag = "OK " if r["ok"] else "BAD"
            extra = ""
            if r["berr"] is not None:
                extra = (f"berr={r['berr']:5.1f}° derr={r['derr']:.2f}m approach={r['approach']:.2f}m "
                         f"mc={r['mc']} nt={r['nt']:.1f} conf={r['conf']:.2f} b2s={r['b2s']:.2f} inl={r['inl']}")
            else:
                extra = f"({r['note']})"
            print(f"    a{idx:<3} closest={r['closest_d']:.2f}m  [{tag}] {extra}")
        # contiguous registrable chain immediately below the pin (blocked by 1st bad anchor)
        chain = 0
        for idx in range(pin-1, 0, -1):
            if idx in results and results[idx]["ok"]:
                chain += 1
            else:
                break
        # longest contiguous registrable run ANYWHERE below the pin, and where the bad ones sit
        longest = cur = 0
        for idx in range(pin-1, 0, -1):
            if idx in results and results[idx]["ok"]:
                cur += 1; longest = max(longest, cur)
            else:
                cur = 0
        bad_idxs = [i for i in below if not results[i]["ok"]]
        n_ok = sum(1 for r in results.values() if r["ok"])
        frac = n_ok/len(results) if results else 0.0
        home_reg = (results.get(1) or {}).get("ok", False) if 1 in results else None
        ep_summary.append((ep, pin, len(below), n_ok, frac, chain, longest, home_reg, bad_idxs))
        print(f"    => {n_ok}/{len(below)} registrable ({frac:.0%}); chain-below-pin={chain}; "
              f"longest-run={longest}; bad anchors={bad_idxs}; "
              f"a1(home)={'reg' if home_reg else 'BAD' if home_reg is not None else 'NA'}\n")

    print(f"{'='*92}\nEPISODE SUMMARY\n{'='*92}")
    print(f"{'ep':>5} {'pin':>4} {'#below':>6} {'#reg':>5} {'frac':>5} {'chain↓':>7} {'longest':>7} {'a1home':>7}  verdict")
    n_route1 = n_vision = n_mixed = 0
    for ep, pin, nb, nok, frac, chain, longest, home, bad in ep_summary:
        # broadly registrable home stretch, blocked only by isolated bad anchors
        # (exactly what a reliability-quarantine that SKIPS a bad `next` is built to fix)
        if frac >= 0.6 and home:
            verdict = f"✅ Route-1: home stretch registrable, blocked by isolated a{bad}"; n_route1 += 1
        elif frac < 0.4:
            verdict = "❌ vision wall: home stretch broadly degenerate"; n_vision += 1
        else:
            verdict = "⚠️ mixed"; n_mixed += 1
        hs = 'reg' if home else ('BAD' if home is not None else 'NA')
        print(f"{ep:>5} a{pin:<3} {nb:>6} {nok:>5} {frac:>4.0%} {chain:>7} {longest:>7} {hs:>7}  {verdict}")
    print(f"\nRoute-1 plausible (skip isolated bad anchor → walk home): {n_route1}/{len(ep_summary)}")
    print(f"Vision wall (broadly degenerate home stretch):            {n_vision}/{len(ep_summary)}")
    print(f"Mixed:                                                    {n_mixed}/{len(ep_summary)}")
    print("(vs the earlier live-only estimate of 1/13 -- this uses real ICP re-matching of the captured clouds)")


if __name__ == "__main__":
    main()
