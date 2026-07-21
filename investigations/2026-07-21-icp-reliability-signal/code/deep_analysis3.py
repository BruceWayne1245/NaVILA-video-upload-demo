import math, statistics
from collections import Counter, defaultdict
from deep_analysis2 import analyze_episode, body_frame_bearing_distance, wrap180
from se2 import wrap_angle

def item3_reconstruction_stats(data):
    pa = data['per_attempt']
    anchor_true_pos = data['anchor_true_pos']
    n_reconstruct = 0
    n_correct = 0
    n_incorrect = 0
    n_reject = 0
    n_reject_should_have = 0
    details = []
    for a in pa:
        c = a['closure']
        if c is None:
            continue
        action = c['action']
        if action in ('reconstruct_next', 'reconstruct_current'):
            n_reconstruct += 1
            role = 'next' if action=='reconstruct_next' else 'current'
            rec = a['next_rec'] if role=='next' else a['current_rec']
            idx = rec['anchor_index']
            rx, ry, ryaw = a['robot_true']
            tx, ty = anchor_true_pos[idx]
            true_bear, true_dist = body_frame_bearing_distance(rx, ry, ryaw, tx, ty)
            # before
            before_dist_err = abs(rec['estimated_distance_to_anchor_m'] - true_dist)
            before_ang_err = abs(wrap180(rec['estimated_bearing_to_anchor_deg'] - true_bear))
            # after (reconstructed dx,dy -> bearing/dist)
            rdx, rdy = c['reconstructed_dx'], c['reconstructed_dy']
            recon_bear = math.degrees(math.atan2(rdy, rdx))
            recon_dist = math.hypot(rdx, rdy)
            after_dist_err = abs(recon_dist - true_dist)
            after_ang_err = abs(wrap180(recon_bear - true_bear))
            improved = (after_dist_err + after_ang_err/50.0) < (before_dist_err + before_ang_err/50.0)
            good_after = after_dist_err < 0.5 and after_ang_err < 30
            is_correct = good_after and improved
            if is_correct:
                n_correct += 1
            else:
                n_incorrect += 1
            details.append(dict(attempt=a['attempt'], role=role, before_dist_err=before_dist_err,
                                 before_ang_err=before_ang_err, after_dist_err=after_dist_err,
                                 after_ang_err=after_ang_err, correct=is_correct))
        elif action == 'reject':
            n_reject += 1
            nrec, crec = a['next_rec'], a['current_rec']
            rx, ry, ryaw = a['robot_true']
            def err_of(rec):
                idx = rec['anchor_index']
                tx, ty = anchor_true_pos[idx]
                tb, td = body_frame_bearing_distance(rx, ry, ryaw, tx, ty)
                de = abs(rec['estimated_distance_to_anchor_m'] - td)
                ae = abs(wrap180(rec['estimated_bearing_to_anchor_deg'] - tb))
                return de, ae
            nde, nae = err_of(nrec)
            cde, cae = err_of(crec)
            n_good = (nde<0.5 and nae<30)
            c_good = (cde<0.5 and cae<30)
            if n_good != c_good:  # exactly one side is trustworthy by ground truth
                n_reject_should_have += 1
    return dict(n_reconstruct=n_reconstruct, n_correct=n_correct, n_incorrect=n_incorrect,
                n_reject=n_reject, n_reject_should_have=n_reject_should_have, details=details)

if __name__ == "__main__":
    import sys
    ep = sys.argv[1] if len(sys.argv)>1 else "4"
    data = analyze_episode(ep)
    r = item3_reconstruction_stats(data)
    print(f"ep{ep}: reconstructions={r['n_reconstruct']} correct={r['n_correct']} incorrect={r['n_incorrect']}")
    print(f"  rejects={r['n_reject']} of which should-have-reconstructed(ground truth shows a clear winner)={r['n_reject_should_have']}")
