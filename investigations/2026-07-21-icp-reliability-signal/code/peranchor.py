import json, math, statistics, pickle
from collections import defaultdict, Counter
import deep_analysis
from paths import build_paths, OUTBOUND_SUCCESS, RETURN_SUCCESS
from deep_analysis2 import analyze_episode

PATHS = build_paths(OUTBOUND_SUCCESS)
def loads_ok(ep):
    try: json.load(open(PATHS[str(ep)][0])); return True
    except: return False
USABLE=[ep for ep in OUTBOUND_SUCCESS if PATHS[str(ep)] and loads_ok(ep)]
deep_analysis.EPISODES.clear()
deep_analysis.EPISODES.update({str(ep):PATHS[str(ep)] for ep in USABLE})

def contiguous(idxs, all_sorted):
    """are the given anchor indices a contiguous block within all_sorted?"""
    if not idxs: return True
    pos=sorted(all_sorted.index(i) for i in idxs)
    return pos==list(range(pos[0],pos[0]+len(pos)))

out={}
for ep in USABLE:
    data=analyze_episode(str(ep))
    icp=data['icp_errors']
    by_anchor=defaultdict(list)
    for e in icp:
        by_anchor[e['role_anchor']].append(e)
    all_sorted=data['sorted_anchor_idx']
    per_anchor={}
    for idx,es in by_anchor.items():
        n=len(es)
        joint=sum(1 for e in es if e['dist_err']<0.5 and e['ang_err']<30)
        per_anchor[idx]=dict(n=n, joint=100*joint/n,
                             mean_ang=statistics.mean(e['ang_err'] for e in es),
                             mean_dist=statistics.mean(e['dist_err'] for e in es))
    # anchors with enough readings
    considered={i:v for i,v in per_anchor.items() if v['n']>=5}
    bad=[i for i,v in considered.items() if v['mean_ang']>45 or v['joint']<30]
    good=[i for i,v in considered.items() if i not in bad]
    out[ep]=dict(grp='SUCC' if ep in RETURN_SUCCESS else 'FAIL',
                 n_anchor=len(considered), n_bad=len(bad),
                 bad=sorted(bad), good_joint=[round(considered[i]['joint']) for i in sorted(good)],
                 contiguous=contiguous(bad, all_sorted),
                 per_anchor={i:considered[i] for i in sorted(considered)},
                 all_sorted=all_sorted,
                 # stall info
                 stall_pin=None)
    # for stuck episodes: which anchor did current pin on, and is it bad?
    cur_seq=[a['rep_current_idx'] for a in data['per_attempt']]
    if cur_seq:
        pin,pinn=Counter(cur_seq).most_common(1)[0]
        out[ep]['stall_pin']=dict(pin=pin, frac=pinn/len(cur_seq),
                                  pin_quality=considered.get(pin))

pickle.dump(out, open('peranchor.pkl','wb'))

print(f"{'ep':>5} {'grp':>4} {'#anchor':>7} {'#bad':>4} {'%bad':>5} {'contig':>6}  bad_anchors(mean_ang°)")
for ep in USABLE:
    o=out[ep]
    badstr=", ".join(f"a{i}({o['per_anchor'][i]['mean_ang']:.0f}°/{o['per_anchor'][i]['joint']:.0f}%j)" for i in o['bad'])
    pct=100*o['n_bad']/o['n_anchor'] if o['n_anchor'] else 0
    print(f"{ep:>5} {o['grp']:>4} {o['n_anchor']:>7} {o['n_bad']:>4} {pct:>4.0f}% {'Y' if o['contiguous'] else 'N':>6}  {badstr}")

print("\n== 汇总: 失败集 vs 成功集的 %坏anchor ==")
for grp in ['SUCC','FAIL']:
    ps=[100*out[ep]['n_bad']/out[ep]['n_anchor'] for ep in USABLE if out[ep]['grp']==grp and out[ep]['n_anchor']]
    print(f"  {grp}: %坏anchor 中位={statistics.median(ps):.0f}%  范围={min(ps):.0f}-{max(ps):.0f}%  (每集: {[round(p) for p in ps]})")

print("\n== 卡死集: pin anchor 是否是坏anchor ==")
for ep in USABLE:
    o=out[ep]; sp=o['stall_pin']
    if sp and sp['frac']>0.5:
        pq=sp['pin_quality']
        q = f"mean_ang={pq['mean_ang']:.0f}° joint={pq['joint']:.0f}%" if pq else "无足够读数"
        print(f"  ep{ep} ({o['grp']}): current 卡在 a{sp['pin']} ({sp['frac']*100:.0f}%的attempt); 该anchor质量: {q}")
