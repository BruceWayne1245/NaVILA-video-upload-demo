import json, math, statistics
from collections import Counter
import deep_analysis
from paths import build_paths
from deep_analysis import load_traj, build_outbound_curve

PIN = {5:11,20:8,319:4,367:11,498:5,500:10,669:4,680:6,813:6,889:9,994:6,1038:4,653:10}
PATHS = build_paths(list(PIN))

def analyze(ep, pin):
    m,t = PATHS[str(ep)]
    rt=json.load(open(m))['round_trip']
    recs=rt['route_relocalization_diagnostics']['covisibility_records']
    by_att={}
    for r in recs: by_att.setdefault(r['attempt'],[]).append(r)
    # per attempt: which anchors were offered (current + next), and their idx gap
    offered_pairs=[]   # (current_idx, next_idx)
    posdis=[]; beardis=[]  # current vs next: position disagreement, bearing disagreement
    for att in sorted(by_att):
        rs=by_att[att]
        idxs=sorted(set(r['anchor_index'] for r in rs), reverse=True)
        if len(idxs)>=2:
            cur, nxt = idxs[0], idxs[1]   # higher idx=current, lower=next
            offered_pairs.append((cur,nxt))
            rc=[r for r in rs if r['anchor_index']==cur][0]
            rn=[r for r in rs if r['anchor_index']==nxt][0]
            # position: compare dx,dy (anchor-frame estimates) -- proxy for quarantine's position_disagreement
            pd=math.hypot(rc['estimated_anchor_dx_m']-rn['estimated_anchor_dx_m'],
                          rc['estimated_anchor_dy_m']-rn['estimated_anchor_dy_m'])
            bd=abs((rc['estimated_bearing_to_anchor_deg']-rn['estimated_bearing_to_anchor_deg']+180)%360-180)
            posdis.append(pd); beardis.append(bd)
    # did the offered NEXT ever skip (next < current-1)? => quarantine fired
    skips=[(c,n) for c,n in offered_pairs if n < c-1]
    gaps=Counter(c-n for c,n in offered_pairs)
    # distinct current values (did current ever advance?)
    currents=[c for c,n in offered_pairs]
    return dict(n=len(offered_pairs),
        distinct_current=sorted(set(currents), reverse=True),
        current_advanced=len(set(currents))>1,
        quarantine_skip_fired=len(skips)>0, n_skips=len(skips),
        gap_distribution=dict(gaps),
        posdis_med=statistics.median(posdis) if posdis else None,
        beardis_med=statistics.median(beardis) if beardis else None,
        posdis_over075=100*sum(1 for p in posdis if p>0.75)/len(posdis) if posdis else None,
        beardis_over30=100*sum(1 for b in beardis if b>30)/len(beardis) if beardis else None,
    )

print(f"{'ep':>5} {'pin':>4} {'attempts':>8} | {'current推进?':>11} {'quarantine跳过?':>14} | "
      f"{'pos不一致中位':>12} {'pos>0.75m占比':>12} | {'bear不一致中位':>13} {'bear>30°占比':>11}")
for ep,pin in PIN.items():
    o=analyze(ep,pin)
    ca = f"{'是' if o['current_advanced'] else '否'}{o['distinct_current']}"
    qf = f"{'是' if o['quarantine_skip_fired'] else '否'}(skip={o['n_skips']},gap={o['gap_distribution']})"
    print(f"{ep:>5} a{pin:<3} {o['n']:>8} | {ca:>11} | {qf}")
    print(f"        pos不一致中位={o['posdis_med']:.2f}m  pos>0.75占比={o['posdis_over075']:.0f}%  |  "
          f"bear不一致中位={o['beardis_med']:.1f}°  bear>30°占比={o['beardis_over30']:.0f}%")
