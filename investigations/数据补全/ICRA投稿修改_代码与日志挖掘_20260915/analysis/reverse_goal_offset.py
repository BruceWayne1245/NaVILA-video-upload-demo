#!/usr/bin/env python3
"""Export auditable reverse-goal metadata. Offset is NOT inferred when absent."""
import argparse, json
from common import *
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default=str(DELIVERY_ROOT/'analysis/reverse_goal_offset.csv')); a=ap.parse_args(); out=[]
    outcomes={r['episode_id']:r for r in read_tsv(TSVS['ON'])}
    for eid,idx in epidx_by_id().items():
        mp=measurement_path(RUNS['ON'],idx); rt={}
        try: rt=json.load(open(mp))['round_trip']
        except Exception: pass
        out.append(dict(episode_id=eid,episode_idx=idx,reverse_provider=rt.get('instruction_rewriter_provider',''),reverse_episode=rt.get('instruction_rewriter_model',''),reverse_goal_offset_to_s0_m='NOT_FOUND',return_success=outcomes[eid].get('return_success',''),distance_to_start_terminal=outcomes[eid].get('distance_to_start','')))
    write_csv(a.output,out)
if __name__=='__main__': main()
