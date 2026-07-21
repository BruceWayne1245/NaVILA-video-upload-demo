import json, math, statistics, sys
from collections import Counter, defaultdict

import deep_analysis, deep_analysis2, deep_analysis4
from paths import build_paths, OUTBOUND_SUCCESS, RETURN_SUCCESS, OLD50
from deep_analysis2 import analyze_episode, body_frame_bearing_distance, wrap180
from deep_analysis3 import item3_reconstruction_stats
from deep_analysis4 import item2_arbiter, item4_stopgate

# ---- override EPISODES in place so all imported modules see it ----
PATHS = build_paths(OUTBOUND_SUCCESS)
USABLE = [ep for ep in OUTBOUND_SUCCESS if PATHS[str(ep)] is not None]
# drop known-corrupt (json.load fails)
def loads_ok(ep):
    try:
        json.load(open(PATHS[str(ep)][0])); return True
    except Exception:
        return False
USABLE = [ep for ep in USABLE if loads_ok(ep)]
deep_analysis.EPISODES.clear()
deep_analysis.EPISODES.update({str(ep): PATHS[str(ep)] for ep in USABLE})

# ---------- user's anchor-selection rubric ----------
def anchor_rubric(pa, anchor_dist, sorted_anchor_idx):
    """For each attempt: rank reported next/current relative to robot true pos s_true.
    ahead = dist < s_true (toward start, return direction). behind = dist >= s_true."""
    next_b = Counter(); cur_b = Counter()
    for a in pa:
        s = a['s_true']
        k = sum(1 for i in sorted_anchor_idx if anchor_dist[i] < s)  # anchors ahead of robot
        def pos(idx): return sorted_anchor_idx.index(idx) if idx in sorted_anchor_idx else None
        pnx = pos(a['rep_next_idx']); pcu = pos(a['rep_current_idx'])
        # NEXT (want ahead, ranks 1-2 correct)
        if pnx is not None:
            if pnx < k:
                ar = k - pnx
                next_b['correct' if ar<=2 else ('slight_overshoot' if ar==3 else 'large_overshoot')] += 1
            else:
                next_b['behind_stale'] += 1
        # CURRENT (want behind, ranks 1-2 correct)
        if pcu is not None:
            if pcu >= k:
                br = pcu - k + 1
                cur_b['correct' if br<=2 else 'lag'] += 1
            else:
                cur_b['ahead_overshoot'] += 1
    return next_b, cur_b

# ---------- stall / progress signal ----------
def stall_signal(pa):
    seq = [(a['attempt'], a['rep_current_idx'], a['robot_true']) for a in pa]
    if not seq: return {}
    cur_seq = [s[1] for s in seq]
    # longest consecutive dwell on a single current idx
    best_len=1; best_idx=cur_seq[0]; cur_len=1
    for i in range(1,len(cur_seq)):
        if cur_seq[i]==cur_seq[i-1]:
            cur_len+=1
            if cur_len>best_len: best_len=cur_len; best_idx=cur_seq[i]
        else: cur_len=1
    # robot motion during that longest dwell (std of position)
    dwell_pts=[s[2] for s in seq if s[1]==best_idx]
    xs=[p[0] for p in dwell_pts]; ys=[p[1] for p in dwell_pts]
    motion_std = (statistics.pstdev(xs)+statistics.pstdev(ys))/2 if len(xs)>1 else 0.0
    most_common_idx, most_common_n = Counter(cur_seq).most_common(1)[0]
    return dict(
        n_attempts=len(seq),
        start_current=cur_seq[0], end_current=cur_seq[-1], min_current=min(cur_seq),
        n_distinct_current=len(set(cur_seq)),
        longest_dwell=best_len, longest_dwell_idx=best_idx,
        longest_dwell_frac=best_len/len(seq),
        most_common_current=most_common_idx, most_common_frac=most_common_n/len(seq),
        motion_std_during_dwell=motion_std,
    )

# ---------- how did the episode end ----------
def ending(ep):
    m,t = deep_analysis.EPISODES[str(ep)]
    rt = json.load(open(m))['round_trip']
    pe = rt['phase_events']
    ev = set(e.get('event') for e in pe)
    timed_out = 'return_timeout' in ev
    # VLM stop attempts during return + gate response
    stops=[]
    gate_by_step={e['step']:e for e in pe if e.get('event')=='stop_gate'}
    for e in pe:
        if e.get('event')=='vlm_command' and e.get('phase')=='return' and 'stop' in str(e.get('output','')).lower():
            g=gate_by_step.get(e['step'])
            stops.append((e['step'], g.get('gate_decision') if g else None, g.get('gate_authority_d') if g else None))
    d2s = rt.get('distance_to_start')
    return dict(timed_out=timed_out, d2s=d2s, n_vlm_stop_attempts=len(stops), vlm_stops=stops[:6])

# ---------- run ----------
def run():
    agg_icp={'success':[], 'fail':[]}
    agg_next={'success':Counter(),'fail':Counter()}
    agg_cur={'success':Counter(),'fail':Counter()}
    per_ep={}
    for ep in USABLE:
        data = analyze_episode(str(ep))
        pa=data['per_attempt']
        grp = 'success' if ep in RETURN_SUCCESS else 'fail'
        # item2 ICP
        icp=data['icp_errors']
        n=len(icp)
        joint=sum(1 for e in icp if e['dist_err']<0.5 and e['ang_err']<30)
        ang10=sum(1 for e in icp if e['ang_err']<10)
        agg_icp[grp].extend((e['dist_err'],e['ang_err']) for e in icp)
        # item1 rubric
        nb,cb = anchor_rubric(pa, data['anchor_dist'], data['sorted_anchor_idx'])
        for kk,vv in nb.items(): agg_next[grp][kk]+=vv
        for kk,vv in cb.items(): agg_cur[grp][kk]+=vv
        # signals
        st=stall_signal(pa)
        recon=item3_reconstruction_stats(data)
        arb=item2_arbiter(str(ep))
        sg=item4_stopgate(str(ep))
        end=ending(ep)
        per_ep[ep]=dict(grp=grp, old=ep in OLD50, n_icp=n,
            icp_joint=100*joint/n if n else 0, icp_ang10=100*ang10/n if n else 0,
            icp_dist_med=statistics.median([e['dist_err'] for e in icp]) if n else None,
            icp_ang_med=statistics.median([e['ang_err'] for e in icp]) if n else None,
            next_b=dict(nb), cur_b=dict(cb), stall=st, recon=recon, arb=arb, sg=sg, end=end)
    return per_ep, agg_icp, agg_next, agg_cur

def pctdict(c):
    tot=sum(c.values()) or 1
    return {k:f"{100*v/tot:.1f}%({v})" for k,v in c.items()}

if __name__=="__main__":
    per_ep, agg_icp, agg_next, agg_cur = run()

    print("="*90)
    print("USABLE 集:", USABLE, f"(共{len(USABLE)}; ep589 损坏已排除)")
    print("return 成功:", [e for e in USABLE if e in RETURN_SUCCESS])
    print("return 失败:", [e for e in USABLE if e not in RETURN_SUCCESS])

    print("\n"+"="*90)
    print("【汇总 item1 锚点身份正确率 (按你的评分规则)】")
    for grp in ['success','fail']:
        nb=agg_next[grp]; cb=agg_cur[grp]
        print(f"\n-- return {grp} --")
        print(f"  NEXT : {pctdict(nb)}")
        print(f"  CURRENT: {pctdict(cb)}")

    print("\n"+"="*90)
    print("【汇总 item2 ICP 精度】")
    for grp in ['success','fail']:
        errs=agg_icp[grp]; n=len(errs)
        joint=sum(1 for d,a in errs if d<0.5 and a<30)
        ang10=sum(1 for d,a in errs if a<10)
        dm=statistics.median([d for d,a in errs]); am=statistics.median([a for d,a in errs])
        print(f"  return {grp}: n={n}  dist<0.5&ang<30 = {100*joint/n:.1f}%  ang<10 = {100*ang10/n:.1f}%  "
              f"(dist中位={dm:.3f}m ang中位={am:.2f}°)")

    print("\n"+"="*90)
    print("【逐集信号表 (return 失败集, 供归因)】")
    hdr=f"{'ep':>5} {'old':>3} {'icp_joint':>9} {'ang10':>6} {'distMed':>7} {'nextCorrect':>11} {'curCorrect':>10} " \
        f"{'minCur':>6} {'dwell%':>6} {'dwellIdx':>8} {'motStd':>7} {'forced':>10} {'gated':>10} {'timedout':>8} {'d2s':>6}"
    print(hdr)
    def cpct(c,key):
        t=sum(c.values()) or 1; return 100*c.get(key,0)/t
    for ep in USABLE:
        if ep in RETURN_SUCCESS: continue
        d=per_ep[ep]; st=d['stall']; arb=d['arb']; sg=d['sg']; end=d['end']
        nb=Counter(d['next_b']); cb=Counter(d['cur_b'])
        print(f"{ep:>5} {'Y' if d['old'] else 'N':>3} {d['icp_joint']:>8.1f}% {d['icp_ang10']:>5.1f}% "
              f"{d['icp_dist_med']:>6.3f}m {cpct(nb,'correct'):>10.1f}% {cpct(cb,'correct'):>9.1f}% "
              f"{st.get('min_current','?'):>6} {100*st.get('longest_dwell_frac',0):>5.1f}% {st.get('longest_dwell_idx','?'):>8} "
              f"{st.get('motion_std_during_dwell',0):>6.3f}m {str(arb['n_forced'])+'/'+str(arb['forced_correct']):>10} "
              f"{str(arb['n_gated'])+'/'+str(arb['gated_should_have_overridden'])+'sh':>10} "
              f"{'Y' if end['timed_out'] else 'N':>8} {(end['d2s'] or -1):>5.2f}")
    print("\n(列说明: nextCorrect/curCorrect=完全正确占比; minCur=return中current推进到的最小锚点(0=起点); "
          "dwell%=最长单锚点停留占比; dwellIdx=卡在哪个锚点; motStd=卡住期间机器人真实位置抖动std(小=机器人几乎没动); "
          "forced=arbiter强制次数/其中方向正确; gated=arbiter放行次数/其中本应override却没有; timedout=是否跑到超时未停; d2s=最终真实离起点距离)")

    print("\n"+"="*90)
    print("【逐集信号表 (return 成功集, 对照)】")
    print(hdr)
    for ep in USABLE:
        if ep not in RETURN_SUCCESS: continue
        d=per_ep[ep]; st=d['stall']; arb=d['arb']; sg=d['sg']; end=d['end']
        nb=Counter(d['next_b']); cb=Counter(d['cur_b'])
        print(f"{ep:>5} {'Y' if d['old'] else 'N':>3} {d['icp_joint']:>8.1f}% {d['icp_ang10']:>5.1f}% "
              f"{d['icp_dist_med']:>6.3f}m {cpct(nb,'correct'):>10.1f}% {cpct(cb,'correct'):>9.1f}% "
              f"{st.get('min_current','?'):>6} {100*st.get('longest_dwell_frac',0):>5.1f}% {st.get('longest_dwell_idx','?'):>8} "
              f"{st.get('motion_std_during_dwell',0):>6.3f}m {str(arb['n_forced'])+'/'+str(arb['forced_correct']):>10} "
              f"{str(arb['n_gated'])+'/'+str(arb['gated_should_have_overridden'])+'sh':>10} "
              f"{'Y' if end['timed_out'] else 'N':>8} {(end['d2s'] or -1):>5.2f}")

    # dump raw per-ep for follow-up
    import pickle
    pickle.dump(per_ep, open('/home/teambruce/scratch_inv/an/per_ep.pkl','wb'))
