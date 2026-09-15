#!/usr/bin/env python3
"""Ground-truth score executed and Policy-V2-blocked hint-action overrides."""
import argparse, json, math, statistics
from common import *

def kind(b):
    # Exact online HintActionArbiterConfig boundaries: <=15 forward, sign otherwise.
    return "forward" if abs(b)<=15.0 else ("left" if b>0 else "right")

def bearing(row, world):
    dx=world[0]-row['position'][0]; dy=world[1]-row['position'][1]; y=row['yaw_rad']
    bx=math.cos(y)*dx+math.sin(y)*dy; by=-math.sin(y)*dx+math.cos(y)*dy
    return math.degrees(math.atan2(by,bx)) if math.hypot(bx,by)>1e-6 else 0.0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('run_dir',nargs='?',default=RUNS['ON']); ap.add_argument('--output',default=str(DELIVERY_ROOT/'analysis/override_correctness_online.csv')); a=ap.parse_args(); out=[]
    outcomes={r['episode_id']:truth(r.get('round_trip_success')) for r in read_tsv(TSVS['ON'])}
    for eid,idx in epidx_by_id().items():
        mp=measurement_path(a.run_dir,idx); anchors={}
        try:
            rt=json.load(open(mp))['round_trip']; anchors={int(x['index']):x['metadata']['world_pose'] for x in rt['route_memory']['anchors'] if x.get('metadata',{}).get('world_pose')}
        except Exception: pass
        wrong_seq=longest=0
        episode_rows=[]
        if not truth(next(x for x in read_tsv(TSVS['ON']) if x['episode_id']==eid).get('outbound_success')): continue
        for r in query_rows(a.run_dir,idx):
            h=r.get('hint_action_arbiter') or {}; ai=h.get('target_anchor_index')
            if ai is None or int(ai) not in anchors: continue
            tb=bearing(r,anchors[int(ai)]); desired=kind(tb)
            blocked=str(h.get('reason','')).startswith('v11_consumer_v2_blocked(')
            if h.get('override') or blocked:
                actual=h.get('desired_kind'); verdict='correct' if actual==desired else 'wrong'
                wrong_seq=wrong_seq+1 if verdict=='wrong' else 0; longest=max(longest,wrong_seq)
                episode_rows.append(dict(episode_id=eid,episode_idx=idx,step=r['step'],record_type=('guard_blocked_override' if blocked else 'executed_override'),target_anchor_index=ai,true_bearing_deg=tb,true_kind=desired,override_kind=actual,verdict=verdict,return_success=int(outcomes[eid])))
        n=len(episode_rows); w=sum(x['verdict']=='wrong' for x in episode_rows)
        for x in episode_rows: x.update(episode_override_count=n,episode_wrong_count=w,episode_wrong_rate=(w/n if n else ''),episode_longest_wrong_run=longest)
        out.extend(episode_rows)
    write_csv(a.output,out)
    print('override/correct/wrong',len(out),sum(x['verdict']=='correct' for x in out),sum(x['verdict']=='wrong' for x in out))
if __name__=='__main__': main()
