#!/usr/bin/env python3
import argparse, json, numpy as np
from common import *

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("run_dir", nargs="?", default=RUNS["ON"]); ap.add_argument("--output",default=str(DELIVERY_ROOT/"analysis/reliability_distributions.csv")); a=ap.parse_args()
    ids=epidx_by_id(); vals={"r_bearing":[],"r_distance":[],"r_pose":[]}
    for idx in ids.values():
        d=result_dir(a.run_dir,idx)
        if not d: continue
        for e in iter_jsonl(d/"reliability_v11_shadow.jsonl"):
            if e.get("event")!="v11_shadow_score": continue
            # authoritative target is the downstream 'next' anchor in this run.
            for o in e.get("outputs",[]):
                if o.get("anchor_role")!="next": continue
                vals["r_bearing"].append(1-float(o["p_bearing_bad_30"]))
                vals["r_distance"].append(1-float(o["p_distance_bad_0p5"]))
                vals["r_pose"].append(1-float(o["p_pose_bad"]))
    rows=[]
    for name,x in vals.items():
        ar=np.asarray(x); q=np.quantile(ar,[.1,.25,.5,.75,.9])
        rows.append(dict(component=name,n=len(ar),min=ar.min(),p10=q[0],p25=q[1],median=q[2],p75=q[3],p90=q[4],max=ar.max(),mean=ar.mean()))
        hist,edges=np.histogram(ar,bins=np.linspace(0,1,21))
        for lo,hi,n in zip(edges[:-1],edges[1:],hist): rows.append(dict(component=name,n=len(ar),bin_left=lo,bin_right=hi,bin_count=n))
    write_csv(a.output,rows,fields=['component','n','min','p10','p25','median','p75','p90','max','mean','bin_left','bin_right','bin_count'])
if __name__=="__main__": main()
