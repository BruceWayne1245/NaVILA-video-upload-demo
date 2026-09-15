#!/usr/bin/env python3
import argparse
from common import *
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default=str(DELIVERY_ROOT/'analysis/table1_common_subset.csv')); a=ap.parse_args()
    tabs={k:{r['episode_id']:r for r in read_tsv(TSVS[k])} for k in ('L','OH','OHA','FO','ON')}; ids=cohort_ids()
    common=[e for e in ids if all(truth(tabs[k][e].get('outbound_success')) for k in tabs)]; rows=[]
    for k,t in tabs.items():
        succ=sum(truth(t[e].get('round_trip_success')) for e in common); arr=sum(truth(t[e].get('return_success')) for e in common)
        rows.append(dict(subset='S_all',config=k,n=len(common),episode_ids=' '.join(common),return_success_n=succ,SR_ret_given_out=(succ/len(common) if common else ''),AR_ret_given_out=(arr/len(common) if common else '')))
    for a1,a2 in zip(('L','OH','OHA','FO'),('OH','OHA','FO','ON')):
        pair=[e for e in ids if truth(tabs[a1][e].get('outbound_success')) and truth(tabs[a2][e].get('outbound_success'))]
        for k in (a1,a2):
            s=sum(truth(tabs[k][e].get('round_trip_success')) for e in pair)
            rows.append(dict(subset=f'{a1}-{a2}',config=k,n=len(pair),episode_ids=' '.join(pair),return_success_n=s,SR_ret_given_out=s/len(pair),AR_ret_given_out=s/len(pair)))
    write_csv(a.output,rows)
if __name__=='__main__': main()
