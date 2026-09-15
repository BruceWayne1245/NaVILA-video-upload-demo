#!/usr/bin/env python3
import argparse, statistics
from common import *

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",default=str(DELIVERY_ROOT/"analysis/stuck_recovery_triggers.csv")); a=ap.parse_args(); rows=[]
    for cfg,run in RUNS.items():
        per=[]; successes_with=0; success_eps=0
        table={r['episode_id']:r for r in read_tsv(TSVS[cfg])}
        for eid,idx in epidx_by_id().items():
            qs=query_rows(run,idx); triggers=sum(1 for r in qs if r.get('stuck_recovery',{}).get('recovery_reason')=='wedge_detected')
            if truth(table.get(eid,{}).get('round_trip_success')): success_eps+=1; successes_with+=int(triggers>0)
            per.append(triggers)
        rows.append(dict(config=cfg,episodes=len(per),total_triggers=sum(per),episodes_triggered=sum(x>0 for x in per),episode_trigger_fraction=sum(x>0 for x in per)/len(per) if per else '',median_triggers_per_episode=statistics.median(per) if per else '',successful_episodes=success_eps,successful_episodes_triggered=successes_with))
    write_csv(a.output,rows)
if __name__=="__main__": main()
