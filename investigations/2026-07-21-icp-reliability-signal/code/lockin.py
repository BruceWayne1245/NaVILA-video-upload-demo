import json, math, statistics, pickle
from collections import Counter
import deep_analysis
from paths import build_paths, OUTBOUND_SUCCESS, RETURN_SUCCESS
from deep_analysis import load_traj, build_outbound_curve, pos_for_distance
from deep_analysis2 import body_frame_bearing_distance, wrap180

PIN = {5:11, 20:8, 319:4, 367:11, 498:5, 500:10, 669:4, 680:6,
       813:6, 889:9, 994:6, 1038:4, 653:10}
PATHS = build_paths(list(PIN))

def num(v):
    try: return float(v)
    except: return None

def analyze(ep, pin):
    m,t = PATHS[str(ep)]
    rt = json.load(open(m))['round_trip']
    traj = load_traj(t); tby = {r['step']:r for r in traj}
    curve = build_outbound_curve(traj)
    recs = rt['route_relocalization_diagnostics']['covisibility_records']
    anchor_dist = {r['anchor_index']: r['anchor_distance_from_start_m'] for r in recs}
    apos = {i: pos_for_distance(curve, d) for i,d in anchor_dist.items()}
    ret0 = min(r['step'] for r in traj if r['phase']=='return')
    tx,ty = apos[pin]
    series=[]
    for r in recs:
        if r['anchor_index']!=pin: continue
        att=r['attempt']; step=ret0+(att-1)*5
        tr=tby.get(step)
        if not tr: continue
        rx,ry,ryaw=tr['position'][0],tr['position'][1],tr['yaw_rad']
        tb,td = body_frame_bearing_distance(rx,ry,ryaw,tx,ty)  # true bearing/dist to pin anchor
        de=abs(r['estimated_distance_to_anchor_m']-td)
        ae=abs(wrap180(r['estimated_bearing_to_anchor_deg']-tb))
        loc=r.get('localizability')
        loc_min = None
        if isinstance(loc,dict):
            vals=[num(x) for x in loc.values() if num(x) is not None]
            loc_min=min(vals) if vals else None
        elif num(loc) is not None: loc_min=num(loc)
        series.append(dict(att=att, true_dist=td, ang=ae, dist=de,
            overlap=num(r.get('overlap_ratio')), corr_deg=num(r.get('corridor_degeneracy_ratio')),
            near_tie=num(r.get('icp_near_tie_basin_count')), conf=num(r.get('confidence')),
            inl=num(r.get('inlier_count')), mclass=r.get('match_class'), loc=loc_min,
            ambig=r.get('icp_ambiguity')))
    series.sort(key=lambda s:s['att'])
    return series

def band(series, sel):
    xs=[s[sel] for s in series if s.get(sel) is not None]
    return xs

out={}
for ep,pin in PIN.items():
    s=analyze(ep,pin)
    if not s: continue
    n=len(s)
    third=max(1,n//3)
    early=s[:third]; late=s[-third:]
    # closest approach
    closest=min(s, key=lambda x:x['true_dist'])
    def mean(lst):
        v=[x for x in lst if x is not None]; return statistics.mean(v) if v else None
    out[ep]=dict(pin=pin, n=n,
        first_dist=s[0]['true_dist'], last_dist=s[-1]['true_dist'], min_dist=closest['true_dist'],
        ang_early=mean([x['ang'] for x in early]), ang_late=mean([x['ang'] for x in late]),
        ang_at_first=s[0]['ang'], ang_at_closest=closest['ang'], dist_at_closest=closest['dist'],
        overlap=mean(band(s,'overlap')), corr_deg=mean(band(s,'corr_deg')),
        near_tie=mean(band(s,'near_tie')), conf=mean(band(s,'conf')), loc=mean(band(s,'loc')),
        mclass=Counter(x['mclass'] for x in s).most_common(3),
        # correlation ang vs true_dist
        )
pickle.dump(out, open('lockin.pkl','wb'))

print(f"{'ep':>5} {'pin':>4} {'n':>4} | {'首次距':>6} {'最近距':>6} {'末次距':>6} | "
      f"{'ang首次':>7} {'ang最近':>7} {'ang早1/3':>8} {'ang晚1/3':>8} | {'overlap':>7} {'corrDeg':>7} {'nearTie':>7} {'loc':>6} {'conf':>5}")
for ep in PIN:
    if ep not in out: continue
    o=out[ep]
    def f(v,w=6,p=2): return f"{v:>{w}.{p}f}" if v is not None else " "*w
    print(f"{ep:>5} a{o['pin']:<3} {o['n']:>4} | {f(o['first_dist'])} {f(o['min_dist'])} {f(o['last_dist'])} | "
          f"{f(o['ang_at_first'],7,1)} {f(o['ang_at_closest'],7,1)} {f(o['ang_early'],8,1)} {f(o['ang_late'],8,1)} | "
          f"{f(o['overlap'],7)} {f(o['corr_deg'],7)} {f(o['near_tie'],7)} {f(o['loc'],6)} {f(o['conf'],5)}")

print("\n== match_class 分布(每集pin锚点) ==")
for ep in PIN:
    if ep not in out: continue
    print(f"  ep{ep} a{out[ep]['pin']}: {out[ep]['mclass']}")

print("\n列说明: 首次/最近/末次距=机器人到pin锚点的真实距离(m); ang最近=机器人离该锚点最近时的角度误差(°);")
print("  H2判据: 即使在最近距 ang 仍很大 + corrDeg高/nearTie>0/overlap低/loc低 => 锚点内在差(从头就差)")
print("  H1判据: ang首次/最近小, 但 ang晚1/3 >> ang早1/3, 且末次距>>首次距 => 机器人走开导致误差涨(锁死后恶化)")
