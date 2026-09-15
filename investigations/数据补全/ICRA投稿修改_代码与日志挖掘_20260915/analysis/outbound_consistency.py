#!/usr/bin/env python3
import argparse, statistics, itertools
from common import *

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output", default=str(DELIVERY_ROOT/"analysis/outbound_consistency_M50.csv")); a=ap.parse_args()
    tables={k:{r["episode_id"]:r for r in read_tsv(v)} for k,v in TSVS.items()}
    ids=cohort_ids(); out=[]
    for eid in ids:
        row={"episode_id":eid,"episode_idx":epidx_by_id()[eid]}
        vals=[]
        for k in RUNS:
            rec=tables[k].get(eid); val=(truth(rec.get("outbound_success")) if rec else None)
            row[k]=("1" if val else "0") if val is not None else "NA"
            if val is not None: vals.append(val)
        row["success_count_6"]=sum(vals); row["all_success_6"]=int(len(vals)==6 and all(vals)); row["all_failure_6"]=int(len(vals)==6 and not any(vals)); row["flipped_6"]=int(len(set(vals))>1)
        if row['flipped_6']:
            seq={k:[(q.get('last_vlm_output'),q.get('command')) for q in query_rows(RUNS[k],row['episode_idx'],'outbound')] for k in RUNS}
            div=[]
            for x,y in itertools.combinations(RUNS,2):
                n=min(len(seq[x]),len(seq[y])); hit=next((i for i in range(n) if seq[x][i]!=seq[y][i]), n if len(seq[x])!=len(seq[y]) else None)
                if hit is not None: div.append((hit,x+'-'+y))
            if div: row['first_action_divergence_query_index'],row['first_action_divergence_pair']=min(div)
        out.append(row)
    write_csv(a.output,out)
    print("per-config",{k:sum(truth(r.get("outbound_success")) for r in tables[k].values() if r["episode_id"] in ids) for k in RUNS})
    print("all_success/all_failure/flipped",sum(int(r['all_success_6']) for r in out),sum(int(r['all_failure_6']) for r in out),sum(int(r['flipped_6']) for r in out))
if __name__=="__main__": main()
