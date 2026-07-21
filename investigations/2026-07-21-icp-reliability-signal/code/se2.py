import math

def wrap_angle(a):
    return math.atan2(math.sin(a), math.cos(a))

def compose_pose(pose, delta):
    x, y, theta = [float(v) for v in pose]
    dx, dy, dtheta = [float(v) for v in delta]
    c, s = math.cos(theta), math.sin(theta)
    return [x + c*dx - s*dy, y + s*dx + c*dy, wrap_angle(theta+dtheta)]

def inverse_delta(delta):
    end_pose = compose_pose([0.0,0.0,0.0], delta)
    x, y, theta = end_pose
    c, s = math.cos(theta), math.sin(theta)
    dxw, dyw = -x, -y
    return [c*dxw + s*dyw, -s*dxw + c*dyw, wrap_angle(-theta)]

def relative_delta(previous_pose, current_pose):
    px, py, pth = [float(v) for v in previous_pose]
    cx, cy, cth = [float(v) for v in current_pose]
    dxw, dyw = cx-px, cy-py
    c, s = math.cos(pth), math.sin(pth)
    return [c*dxw + s*dyw, -s*dxw + c*dyw, wrap_angle(cth-pth)]

def oracle_edge_between(anchor_pose, from_idx, to_idx):
    """anchor_pose: dict idx -> [x,y,yaw]. Mirrors _oracle_edge_between."""
    return relative_delta(anchor_pose[from_idx], anchor_pose[to_idx])

def reproject_delta_to_anchor(anchor_pose, source_idx, dx, dy, dtheta, target_idx):
    target_pose_in_source_frame = oracle_edge_between(anchor_pose, source_idx, target_idx)
    current_pose_in_source_frame = inverse_delta([dx, dy, dtheta])
    return relative_delta(current_pose_in_source_frame, target_pose_in_source_frame)

POS_THRESH_M = 0.75
HEAD_THRESH_RAD = math.radians(30.0)
QUALITY_RATIO = 1.5

def reconciliation_disagreement_bearing(a_dx, a_dy, a_dtheta, b_dx, b_dy, b_dtheta):
    bearing_a = math.atan2(a_dy, a_dx)
    bearing_b = math.atan2(b_dy, b_dx)
    return abs(wrap_angle(bearing_b - bearing_a))

def closure_precheck(anchor_pose, next_rec, current_rec):
    """next_rec = lower anchor_index (a), current_rec = higher anchor_index (b).
    Faithful replay of _sequential_pair_closure_precheck (threshold mode,
    reconciliation_signal=bearing), using ORACLE (ground-truth) anchor edges
    in place of the live 'accumulated' edge chain (justified: 1-hop apart,
    negligible drift -- same substitution this project's own team used).
    Returns dict with: disagreement flags, action ('agree'/'reconstruct_next'/
    'reconstruct_current'/'reject'), and reconstructed (dx,dy,dtheta) if any.
    """
    a_idx = next_rec['anchor_index']; b_idx = current_rec['anchor_index']
    a_dx, a_dy = next_rec['estimated_anchor_dx_m'], next_rec['estimated_anchor_dy_m']
    a_dtheta = math.radians(next_rec['estimated_anchor_dtheta_deg'])
    b_dx, b_dy = current_rec['estimated_anchor_dx_m'], current_rec['estimated_anchor_dy_m']
    b_dtheta = math.radians(current_rec['estimated_anchor_dtheta_deg'])

    reproj_b = reproject_delta_to_anchor(anchor_pose, b_idx, b_dx, b_dy, b_dtheta, a_idx)
    rdx, rdy, rdtheta = reproj_b
    position_disagreement = math.hypot(rdx-a_dx, rdy-a_dy)
    heading_disagreement = reconciliation_disagreement_bearing(a_dx, a_dy, a_dtheta, rdx, rdy, rdtheta)

    if position_disagreement <= POS_THRESH_M and heading_disagreement <= HEAD_THRESH_RAD:
        return dict(action='agree', position_disagreement=position_disagreement,
                    heading_disagreement=heading_disagreement)

    a_quality = float(next_rec['confidence']) * math.sqrt(max(1, int(next_rec.get('inlier_count') or 1)))
    b_quality = float(current_rec['confidence']) * math.sqrt(max(1, int(current_rec.get('inlier_count') or 1)))

    if b_quality > QUALITY_RATIO * a_quality:
        return dict(action='reconstruct_next', position_disagreement=position_disagreement,
                     heading_disagreement=heading_disagreement,
                     reconstructed_dx=rdx, reconstructed_dy=rdy, reconstructed_dtheta=rdtheta,
                     a_quality=a_quality, b_quality=b_quality)
    if a_quality > QUALITY_RATIO * b_quality:
        reproj_a = reproject_delta_to_anchor(anchor_pose, a_idx, a_dx, a_dy, a_dtheta, b_idx)
        rdx2, rdy2, rdtheta2 = reproj_a
        return dict(action='reconstruct_current', position_disagreement=position_disagreement,
                     heading_disagreement=heading_disagreement,
                     reconstructed_dx=rdx2, reconstructed_dy=rdy2, reconstructed_dtheta=rdtheta2,
                     a_quality=a_quality, b_quality=b_quality)
    return dict(action='reject', position_disagreement=position_disagreement,
                heading_disagreement=heading_disagreement, a_quality=a_quality, b_quality=b_quality)
