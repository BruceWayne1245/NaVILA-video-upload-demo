#!/usr/bin/env python3
import argparse, json
from common import *
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('run_dir',nargs='?',default=RUNS['FO']); ap.add_argument('--output',default=str(DELIVERY_ROOT/'analysis/terminal_verifier_events.csv')); a=ap.parse_args(); out=[]
    # Operates on the matched M50 IDs but accepts any run tag.
    for eid,idx in epidx_by_id().items():
        for r in query_rows(a.run_dir,idx):
            g=r.get('stop_gate') or {}; decision=g.get('gate_decision')
            if decision and decision!='pass': out.append(dict(episode_id=eid,episode_idx=idx,step=r['step'],decision=decision,true_distance_to_s0_m=r.get('distance_to_start_m'),gate_authority_d=g.get('gate_authority_d'),gate_conf=g.get('gate_conf'),gate_anchor_route_remaining_m=g.get('gate_anchor_route_remaining_m'),gate_anchor_close_streak=g.get('gate_anchor_close_streak'),vlm_output=r.get('last_vlm_output')))
    write_csv(a.output,out)
    from collections import Counter; print(Counter(x['decision'] for x in out))
if __name__=='__main__': main()
