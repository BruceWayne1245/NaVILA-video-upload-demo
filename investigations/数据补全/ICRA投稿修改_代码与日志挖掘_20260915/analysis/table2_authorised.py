#!/usr/bin/env python3
import argparse, collections
from common import *

def classify(h):
    reason=h.get('reason')
    if reason=='target_too_close': return 'target-anchor-too-close'
    if reason=='vlm_action_consistent': return 'action-consistent'
    if h.get('override'): return 'conflict-overridden'
    if str(reason).startswith('v11_consumer_v2_blocked('): return 'conflict-not-traversable'
    if reason in ('occupied_in_local_map_path','occupied_in_hint_path','no_clear_path'): return 'conflict-not-traversable'
    return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default=str(DELIVERY_ROOT/'analysis/table2_authorised_denominator.csv')); a=ap.parse_args(); rows=[]
    for cfg in ('ON','OHA'):
        counts=collections.Counter(); total=0; auth=0
        table={r['episode_id']:r for r in read_tsv(TSVS[cfg])}
        for eid,idx in epidx_by_id().items():
            if cfg=='ON' and not truth(table[eid].get('outbound_success')): continue
            for r in query_rows(RUNS[cfg],idx):
                h=r.get('hint_action_arbiter');
                if not h: continue
                total+=1; c=classify(h)
                # Online code checks target-too-close before the 0.90 confidence gate.
                # Therefore "authorised" means it did not return low-confidence,
                # not simply confidence>=.90 (the 30-step difference in the paper).
                authorised=(cfg=='OHA' or h.get('reason')!='low_relocalization_confidence')
                if authorised: auth+=1; counts[c]+=bool(c)
        nonclose=auth-counts['target-anchor-too-close']
        for denominator,n in [('authorised_all',auth),('authorised_not_close',nonclose)]:
            for category in ('action-consistent','conflict-not-traversable','conflict-overridden','target-anchor-too-close'):
                v=counts[category]
                excluded=(denominator=='authorised_not_close' and category=='target-anchor-too-close')
                rows.append(dict(config=cfg,total_return_decisions=total,denominator=denominator,denominator_n=n,category=category,count=('excluded' if excluded else v),percent=('n/a' if excluded else (100*v/n if n else ''))))
    write_csv(a.output,rows)
if __name__=='__main__': main()
