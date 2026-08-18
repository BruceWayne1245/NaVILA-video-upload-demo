"""Stuck / wedge recovery for the return phase (2026-07-22, opt-in, off by default).

Motivation (investigations/2026-07-22, ep5/ep653/ep491): the low-level go2
locomotion can drive the robot into a wall/dead-corner where a commanded
forward produces ~0 net motion (ep5: cmd 0.50 m/s, actual 0.026), and the VLM
then loops (forward or turn) forever without escaping -- or spins in place
(ep491). No relocalization/hint fix helps once wedged (ep5 keeps 0 mm even with
a 1-6 deg-accurate hint). This module DETECTS the no-net-progress state and
scripts a back-out (reverse ~180 deg, drive out, hand back to the VLM), which is
the only thing that frees a physically wedged base.

Detector (validated offline on 20 episodes, GH investigation): fire when
`n_queries` consecutive VLM queries each moved the base < `move_min_m`, AND the
believed distance-to-home is > `belief_far_min_m` (stuck-near-home is handled by
stop_gate, not by backing away), AND the VLM is not currently trying to stop
(guards the ep813 confidently-wrong-tracker-at-home case). Zero false positives
on the 9 successful episodes at n_queries>=6 / move_min=0.15 / belief_far=5.0.

This is a pure locomotion supervisor: it never touches relocalization,
promotion, quarantine, or the stop decision. With `enabled=False` it is inert.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def _wrap_pi(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


@dataclass
class StuckRecoveryConfig:
    enabled: bool = False
    move_min_m: float = 0.15          # per-VLM-query net displacement below this = "no progress"
    n_queries: int = 8                # consecutive no-progress queries before triggering
    belief_far_min_m: float = 5.0     # only trigger when believed this far from home
    turn_step_deg: float = 45.0       # magnitude of each scripted turn action
    forward_step_cm: float = 75.0     # magnitude of each scripted forward action
    reverse_turn_deg: float = 180.0   # how far to turn to reverse before escaping
    turn_tol_deg: float = 25.0        # "faced target" tolerance
    escape_forward_m: float = 0.8     # net displacement that counts as escaped
    max_recovery_queries: int = 16    # cap on one recovery attempt (both phases)
    max_attempts: int = 5             # cap on recovery attempts per episode
    face_next_after: bool = True      # after escaping, turn toward `next` before handing back
    # 2026-07-22: a wedge can physically block rotation in ONE direction (wall on that
    # side). If the base fails to rotate (yaw change < yaw_progress_min_deg) for
    # flip_after_queries consecutive queries while reversing, flip the turn direction --
    # the other way may be unblocked. Target is antipodal (~180 deg) so either direction
    # still reaches the reversed heading. Confirmed necessary by the ep5 live smoke, where
    # a fixed "turn left" spun the command 13x with the base never rotating out.
    flip_after_queries: int = 2       # no-yaw-progress queries before flipping turn direction
    yaw_progress_min_deg: float = 12.0  # per-query yaw change below this = "not rotating"


@dataclass
class StuckRecoveryDecision:
    active: bool                       # is recovery currently driving?
    override: bool                     # should replacement_output replace the VLM action?
    replacement_output: Optional[str]
    state: str                         # normal|reverse_turn|escape_forward|face_next
    reason: str
    stuck_queries: int
    attempts_used: int

    def as_log_dict(self) -> dict:
        return {
            "recovery_active": bool(self.active),
            "recovery_override": bool(self.override),
            "recovery_state": self.state,
            "recovery_reason": self.reason,
            "recovery_stuck_queries": int(self.stuck_queries),
            "recovery_attempts_used": int(self.attempts_used),
            "recovery_replacement_output": self.replacement_output,
        }


class StuckRecovery:
    """Call check() exactly once per return-phase VLM query."""

    def __init__(self, cfg: Optional[StuckRecoveryConfig] = None):
        self.cfg = cfg or StuckRecoveryConfig()
        self._last_pos: Optional[tuple] = None
        self._no_progress = 0
        self._state = "normal"
        self._attempts = 0
        self._rec_queries = 0
        self._target_yaw: Optional[float] = None      # reverse heading target
        self._reverse_left: Optional[bool] = None     # committed turn direction (True=left)
        self._reverse_last_yaw: Optional[float] = None
        self._reverse_stuck = 0                        # consecutive no-yaw-progress queries
        self._escape_start: Optional[tuple] = None
        self._next_yaw_target: Optional[float] = None  # world yaw to face `next`

    # --- scripted action strings (match parse_vlm_command / arbiter format) ---
    def _forward(self) -> str:
        return f"The next action is move forward {int(self.cfg.forward_step_cm)} cm."

    def _turn(self, left: bool) -> str:
        side = "left" if left else "right"
        return f"The next action is turn {side} {int(self.cfg.turn_step_deg)} degree."

    def _turn_toward(self, cur_yaw: float, target_yaw: float) -> str:
        err = _wrap_pi(target_yaw - cur_yaw)
        return self._turn(left=err > 0)

    def _reset_to_normal(self):
        self._state = "normal"
        self._rec_queries = 0
        self._target_yaw = None
        self._reverse_left = None
        self._reverse_last_yaw = None
        self._reverse_stuck = 0
        self._escape_start = None
        self._next_yaw_target = None
        self._no_progress = 0  # give the freshly-recovered robot a clean slate

    def check(self, robot_position, robot_yaw_rad: float, believed_distance_m: Optional[float],
              bearing_to_next_deg: Optional[float], vlm_is_stopping: bool) -> StuckRecoveryDecision:
        cfg = self.cfg
        pos = (float(robot_position[0]), float(robot_position[1]))
        if not cfg.enabled:
            self._last_pos = pos
            return StuckRecoveryDecision(False, False, None, "normal", "disabled", 0, self._attempts)

        # ---- already recovering: advance the scripted state machine ----
        if self._state != "normal":
            self._rec_queries += 1
            if self._rec_queries > cfg.max_recovery_queries:
                # this attempt exhausted; hand back (attempt already counted).
                self._reset_to_normal()
                self._last_pos = pos
                return StuckRecoveryDecision(False, False, None, "normal",
                                             "recovery_exhausted", 0, self._attempts)
            if self._state == "reverse_turn":
                if abs(_wrap_pi(robot_yaw_rad - self._target_yaw)) <= math.radians(cfg.turn_tol_deg):
                    self._state = "escape_forward"
                    self._escape_start = pos
                    self._last_pos = pos
                    return StuckRecoveryDecision(True, True, self._forward(), "escape_forward",
                                                 "reversed_now_escaping", 0, self._attempts)
                # detect "cannot rotate this way" and flip direction (ep5 wedge)
                reason = "turning_to_reverse"
                if self._reverse_last_yaw is not None:
                    yaw_delta = abs(_wrap_pi(robot_yaw_rad - self._reverse_last_yaw))
                    if yaw_delta < math.radians(cfg.yaw_progress_min_deg):
                        self._reverse_stuck += 1
                    else:
                        self._reverse_stuck = 0
                    if self._reverse_stuck >= cfg.flip_after_queries:
                        self._reverse_left = not self._reverse_left
                        self._reverse_stuck = 0
                        reason = "flipped_turn_direction"
                self._reverse_last_yaw = robot_yaw_rad
                self._last_pos = pos
                return StuckRecoveryDecision(True, True, self._turn(left=self._reverse_left),
                                             "reverse_turn", reason, 0, self._attempts)
            if self._state == "escape_forward":
                moved = math.hypot(pos[0] - self._escape_start[0], pos[1] - self._escape_start[1])
                if moved >= cfg.escape_forward_m:
                    if cfg.face_next_after and bearing_to_next_deg is not None:
                        self._next_yaw_target = _wrap_pi(robot_yaw_rad + math.radians(bearing_to_next_deg))
                        self._state = "face_next"
                        self._last_pos = pos
                        return StuckRecoveryDecision(True, True,
                                                     self._turn_toward(robot_yaw_rad, self._next_yaw_target),
                                                     "face_next", "escaped_now_facing_next", 0, self._attempts)
                    self._reset_to_normal()
                    self._last_pos = pos
                    return StuckRecoveryDecision(False, False, None, "normal", "escaped", 0, self._attempts)
                self._last_pos = pos
                return StuckRecoveryDecision(True, True, self._forward(), "escape_forward",
                                             "escaping", 0, self._attempts)
            if self._state == "face_next":
                if abs(_wrap_pi(robot_yaw_rad - self._next_yaw_target)) <= math.radians(cfg.turn_tol_deg):
                    self._reset_to_normal()
                    self._last_pos = pos
                    return StuckRecoveryDecision(False, False, None, "normal", "recovered", 0, self._attempts)
                act = self._turn_toward(robot_yaw_rad, self._next_yaw_target)
                self._last_pos = pos
                return StuckRecoveryDecision(True, True, act, "face_next", "facing_next", 0, self._attempts)

        # ---- normal: run the detector ----
        net = math.hypot(pos[0] - self._last_pos[0], pos[1] - self._last_pos[1]) if self._last_pos else None
        self._last_pos = pos
        if net is None:
            return StuckRecoveryDecision(False, False, None, "normal", "first_query", 0, self._attempts)
        if net < cfg.move_min_m:
            self._no_progress += 1
        else:
            self._no_progress = 0

        far = believed_distance_m is not None and believed_distance_m > cfg.belief_far_min_m
        can_attempt = self._attempts < cfg.max_attempts
        if (self._no_progress >= cfg.n_queries and far and not vlm_is_stopping and can_attempt):
            # trigger recovery: reverse ~180 deg from the wedge heading, then escape.
            self._attempts += 1
            self._target_yaw = _wrap_pi(robot_yaw_rad + math.radians(cfg.reverse_turn_deg))
            self._state = "reverse_turn"
            self._rec_queries = 0
            # commit to the shortest-path turn direction; flipped later if it can't rotate.
            self._reverse_left = _wrap_pi(self._target_yaw - robot_yaw_rad) > 0
            self._reverse_last_yaw = robot_yaw_rad
            self._reverse_stuck = 0
            return StuckRecoveryDecision(True, True, self._turn(left=self._reverse_left),
                                         "reverse_turn", "wedge_detected",
                                         self._no_progress, self._attempts)

        # not (yet) triggering
        reason = "monitoring"
        if self._no_progress >= cfg.n_queries and not far:
            reason = "stuck_but_near_home"
        elif self._no_progress >= cfg.n_queries and vlm_is_stopping:
            reason = "stuck_but_vlm_stopping"
        elif self._no_progress >= cfg.n_queries and not can_attempt:
            reason = "stuck_but_attempts_exhausted"
        return StuckRecoveryDecision(False, False, None, "normal", reason, self._no_progress, self._attempts)
