import json, math, statistics
from collections import Counter
from deep_analysis import EPISODES
from deep_analysis2 import analyze_episode
from deep_analysis3 import item3_reconstruction_stats
from deep_analysis4 import item2_arbiter, item4_stopgate

def pct(lst, cond):
    return 100.0*sum(1 for x in lst if cond(x))/len(lst) if lst else float('nan')

results = {}
for ep in EPISODES:
    data = analyze_episode(ep)
    pa = data['per_attempt']
    rt = data['rt']

    cur_off = [a['current_anchor_offset'] for a in pa if a['current_anchor_offset'] is not None]
    cur_m = [a['current_dist_err_m'] for a in pa]

    de = [e['dist_err'] for e in data['icp_errors']]
    ae = [e['ang_err'] for e in data['icp_errors']]
    both = sum(1 for e in data['icp_errors'] if e['dist_err']<0.5 and e['ang_err']<30)
    ang10 = sum(1 for e in data['icp_errors'] if e['ang_err']<10)
    n_icp = len(data['icp_errors'])

    r3 = item3_reconstruction_stats(data)
    r2 = item2_arbiter(ep)
    r4 = item4_stopgate(ep)

    results[ep] = dict(
        round_trip_success=rt['round_trip_success'],
        distance_to_start=rt['distance_to_start'],
        n_attempts=len(pa),
        anchor_exact_pct=pct(cur_off, lambda x: x==0),
        anchor_off1_pct=pct(cur_off, lambda x: abs(x)==1),
        anchor_off2plus_pct=pct(cur_off, lambda x: abs(x)>=2),
        anchor_mean_m=statistics.mean(cur_m) if cur_m else None,
        anchor_median_m=statistics.median(cur_m) if cur_m else None,
        icp_n=n_icp,
        icp_joint_pct=100*both/n_icp if n_icp else None,
        icp_ang10_pct=100*ang10/n_icp if n_icp else None,
        icp_dist_median=statistics.median(de) if de else None,
        icp_ang_median=statistics.median(ae) if ae else None,
        recon_n=r3['n_reconstruct'], recon_correct=r3['n_correct'], recon_incorrect=r3['n_incorrect'],
        reject_n=r3['n_reject'], reject_should_have=r3['n_reject_should_have'],
        arb_forced=r2['n_forced'], arb_forced_correct=r2['forced_correct'],
        arb_gated=r2['n_gated'], arb_gated_exec_correct=r2['gated_executed_correct'],
        arb_gated_should_have=r2['gated_should_have_overridden'],
        arb_noop=r2['n_noop'],
        sg_decisions=r4['decisions'], sg_final_dist=r4['final_true_dist'],
    )

print(json.dumps(results, indent=2, default=str))
