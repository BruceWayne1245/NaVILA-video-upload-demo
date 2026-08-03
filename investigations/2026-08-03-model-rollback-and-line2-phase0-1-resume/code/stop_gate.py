"""Return-phase stop arbitration layer (stop gate).

Sits between the VLM output and the terminal-condition check in
round_trip_eval.py.  Does NOT modify hint generation, anchor selection, or
particle filtering — it only reads the authoritative distance/confidence from
the route-memory pipeline and decides whether to:

  ACCEPTED  VLM issued stop, high conf, d ≤ r_in  → execute stop
  VETOED    VLM issued stop, high conf, d > r_out  → suppress stop, inject
            a non-zero forward/bearing command so the robot keeps moving
  DEFERRED  VLM issued stop, low conf OR r_in < d ≤ r_out → pass through
  FORCED    VLM did NOT issue stop, high conf, d ≤ r_in for ≥ confirm_steps
            consecutive VLM-query steps → trigger terminal
  PASS      Gate not applicable (no progress, teleport frame, etc.)

Anchor corroboration (2026-07-19, opt-in via anchor_corroboration_enabled):
low confidence used to mean "defer to the VLM unconditionally", even when the
reported distance was wildly implausible -- confirmed live on 4 episodes of
canonical_report_next_50ep_20260719_accumulated (ep187, ep498, ep589, ep678)
where the VLM's stop was accepted 4.5-14m from the true start purely because
confidence dipped a hair below min_confidence at the critical attempt, with
no fallback. The route-memory anchor currently tracked as "current" carries
its own distance-from-start (anchor_route_remaining_m), fixed once at anchor
creation and NOT re-measured every attempt, so it doesn't inherit THIS
attempt's ICP noise the way distance_to_start_m's live distance-to-anchor
component does. When it agrees with the (otherwise-untrusted) current
reading, that agreement is used to bypass min_confidence in two directions:
  - veto a stop even at low confidence, when the anchor itself isn't a
    "close" one AND the current reading is also clearly beyond r_out
    (confirmed against all 4 episodes above: anchor_route_remaining_m was
    3.0-12.1m at the moment of the bad stop -- never a close anchor).
  - force a stop even at low confidence, but only after several consecutive
    attempts where the anchor AND the current reading agree the robot is
    home (a single agreement is not enough -- see ep319 in
    [[project_navila_isaac]]: a "close" anchor's identity can survive after
    the robot has since drifted away from it, e.g. via terrain/contact
    dynamics, so a stale one-time promotion must not be trusted on its own).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GateDecision:
    decision: str                         # "pass"|"accepted"|"vetoed"|"forced"|"deferred"
    authority_d: Optional[float]          # authoritative distance used (m), None if unavailable
    conf: float                           # confidence used for the decision
    is_teleport_frame: bool               # True if this VLM step followed a teleport sim-step
    suggested_command: Optional[List[float]] = None  # [vx, vy, vyaw] injected when vetoed
    suggested_steps: int = 10            # env sim-steps for the injected command
    # 2026-08-03 (line-2 Phase 0.1 diagnostic, mechanism D): which anchor ROLE
    # ("next"/"current") and index the corroboration inputs (anchor_route_remaining)
    # came from this decision -- purely observational, see RelativeStartProgress
    # .anchor_progress_role's docstring in route_memory_agent.py for why this
    # was added (ep205's mismatch between the offline-reconstructed anchor and
    # what stop_gate actually saw could not otherwise be told apart after the fact).
    anchor_progress_role: Optional[str] = None
    anchor_index: Optional[int] = None
    anchor_route_remaining: Optional[float] = None
    # 2026-08-03 (line-2 Phase 0.2 diagnostic): the actual internal CURRENT
    # index and eviction's own live state -- anchor_index/anchor_progress_role
    # above can point at "next" (see RelativeStartProgress.anchor_progress_role's
    # docstring), so they cannot be used to tell whether eviction ever fires.
    current_anchor_index: Optional[int] = None
    current_anchor_unreliable: Optional[bool] = None
    current_evict_streak: Optional[int] = None

    def as_log_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "gate_decision": self.decision,
            "gate_authority_d": self.authority_d,
            "gate_conf": round(self.conf, 4),
            "gate_teleport_filtered": self.is_teleport_frame,
            "gate_anchor_progress_role": self.anchor_progress_role,
            "gate_anchor_index": self.anchor_index,
            "gate_anchor_route_remaining": self.anchor_route_remaining,
            "gate_current_anchor_index": self.current_anchor_index,
            "gate_current_anchor_unreliable": self.current_anchor_unreliable,
            "gate_current_evict_streak": self.current_evict_streak,
        }
        if self.suggested_command is not None:
            d["gate_suggested_command"] = [round(x, 4) for x in self.suggested_command]
        return d


class ReturnStopGate:
    """Stop arbitration for the return phase.

    Parameters
    ----------
    r_in :
        Inner radius (m). Stops at d ≤ r_in are accepted; forced-stop
        counter increments when d ≤ r_in (high conf, no teleport).
    r_out :
        Outer radius (m). Stops at d > r_out are vetoed (high conf).
    confirm_steps :
        Consecutive VLM-query steps where d ≤ r_in before forcing terminal
        (guards against a VLM that never issues stop).
    min_confidence :
        Minimum confidence ∈ [0, 1] to exercise veto/accept/force authority.
        Below this threshold the gate defers to the VLM.
    anchor_corroboration_enabled :
        Off by default. When on, the anchor currently tracked as "current"
        (its own distance-from-start, fixed at anchor creation) can bypass
        min_confidence in both directions -- see module docstring.
    forced_stop_anchor_confirm_steps :
        Consecutive VLM-query steps where the anchor's own distance AND the
        current (otherwise-untrusted) reading both agree the robot is within
        r_in, before an anchor-corroborated forced stop fires. Deliberately
        separate from (and typically smaller than) confirm_steps -- see
        module docstring for why a streak, not a single agreement, is
        required.
    """

    _TELEPORT_JUMP_M: float = 3.0   # jump above this in one sim step → teleport

    def __init__(
        self,
        r_in: float = 3.0,
        r_out: float = 3.0,
        confirm_steps: int = 3,
        min_confidence: float = 0.5,
        anchor_corroboration_enabled: bool = False,
        forced_stop_anchor_confirm_steps: int = 2,
    ) -> None:
        if r_in > r_out:
            raise ValueError(f"r_in ({r_in}) must be ≤ r_out ({r_out})")
        self.r_in = float(r_in)
        self.r_out = float(r_out)
        self.confirm_steps = int(confirm_steps)
        self.min_confidence = float(min_confidence)
        self.anchor_corroboration_enabled = bool(anchor_corroboration_enabled)
        self.forced_stop_anchor_confirm_steps = int(forced_stop_anchor_confirm_steps)

        self._confirm_count: int = 0
        self._anchor_close_streak: int = 0
        self._prev_sim_pos: Optional[List[float]] = None  # [x, y]
        self._teleport_pending: bool = False

    # ------------------------------------------------------------------
    # Sim-step hook — call after every env.step() for teleport detection
    # ------------------------------------------------------------------

    def notify_sim_step(self, current_pos) -> bool:
        """Update position history and detect teleport.

        Call at every simulation step (after env.step) with the robot's
        current [x, y, z] position.  Returns True if this step is a teleport.
        """
        x, y = float(current_pos[0]), float(current_pos[1])

        if self._prev_sim_pos is None:
            self._prev_sim_pos = [x, y]
            return False

        dx = x - self._prev_sim_pos[0]
        dy = y - self._prev_sim_pos[1]
        is_teleport = math.sqrt(dx * dx + dy * dy) > self._TELEPORT_JUMP_M

        self._prev_sim_pos = [x, y]

        if is_teleport:
            self._teleport_pending = True
            self._confirm_count = 0   # teleport invalidates confirm streak
            self._anchor_close_streak = 0

        return is_teleport

    # ------------------------------------------------------------------
    # VLM-step arbiter — call at each VLM query during return phase
    # ------------------------------------------------------------------

    def check(
        self,
        progress,               # RelativeStartProgress | None
        vlm_issued_stop: bool,
    ) -> GateDecision:
        """Arbitrate stop/continue at a VLM query step.

        Parameters
        ----------
        progress :
            ``RelativeStartProgress`` (or duck-typed equivalent) produced by
            ``route_progress_override`` / ``RouteMemoryAgent.progress()``, or
            ``None`` when route memory is unavailable.
        vlm_issued_stop :
            Whether the VLM issued a stop command at this query step.
        """
        is_teleport = self._teleport_pending
        self._teleport_pending = False

        d, conf = self._extract_d_and_conf(progress)
        bearing_deg: Optional[float] = getattr(progress, "bearing_to_start_deg", None)
        anchor_route_remaining: Optional[float] = getattr(progress, "anchor_route_remaining_m", None)
        # Injection C (2026-07-21): the estimate behind this distance/bearing was
        # flagged low-reliability by route-memory (its own absolute U >=
        # threshold). Defer to the VLM's own stop decision rather than vetoing it
        # on an untrusted "you're far" reading -- the ep680 class, where a pinned
        # current over-reported distance and the gate suppressed 258 correct
        # within-radius stops. Anchor-corroborated FORCE (which relies on the
        # anchor's own fixed distance-from-start, not this noisy reading) is left
        # intact below.
        distance_authority_low_reliability: bool = bool(
            getattr(progress, "distance_authority_low_reliability", False)
        )
        # 2026-08-03 diagnostic (see GateDecision.anchor_progress_role's docstring).
        anchor_progress_role: Optional[str] = getattr(progress, "anchor_progress_role", None)
        anchor_idx: Optional[int] = getattr(progress, "target_anchor_index", None)
        current_anchor_idx: Optional[int] = getattr(progress, "current_target_anchor_index", None)
        current_anchor_unreliable: Optional[bool] = getattr(progress, "current_anchor_unreliable", None)
        current_evict_streak: Optional[int] = getattr(progress, "current_evict_streak", None)
        _diag = dict(
            anchor_progress_role=anchor_progress_role,
            anchor_index=anchor_idx,
            anchor_route_remaining=anchor_route_remaining,
            current_anchor_index=current_anchor_idx,
            current_anchor_unreliable=current_anchor_unreliable,
            current_evict_streak=current_evict_streak,
        )

        # No authoritative distance → cannot arbitrate
        if d is None:
            self._confirm_count = 0
            self._anchor_close_streak = 0
            return GateDecision("pass", None, conf if conf else 0.0, is_teleport, **_diag)

        # Teleport frame: don't count toward arrival, don't arbitrate
        if is_teleport:
            return GateDecision("pass", d, conf, is_teleport, **_diag)

        high_conf = conf >= self.min_confidence

        # Update forced-stop confirm counter
        if high_conf and d <= self.r_in:
            self._confirm_count += 1
        else:
            self._confirm_count = 0

        # Anchor-corroborated evidence for a missed arrival (see module
        # docstring): the anchor's own fixed distance-from-start and this
        # attempt's own (otherwise-untrusted) reading must BOTH say "home"
        # for this attempt to count -- a single agreement isn't enough, see
        # forced_stop_anchor_confirm_steps's docstring.
        anchor_confirms_close = (
            anchor_route_remaining is not None
            and anchor_route_remaining <= self.r_in
            and d <= self.r_in
        )
        if anchor_confirms_close:
            self._anchor_close_streak += 1
        else:
            self._anchor_close_streak = 0

        # --- Forced stop: robot near start long enough, VLM never stopped ---
        anchor_forces = (
            self.anchor_corroboration_enabled
            and self._anchor_close_streak >= self.forced_stop_anchor_confirm_steps
        )
        if not vlm_issued_stop and ((high_conf and self._confirm_count >= self.confirm_steps) or anchor_forces):
            return GateDecision("forced", d, conf, is_teleport, **_diag)

        # Nothing to arbitrate when VLM did not stop
        if not vlm_issued_stop:
            return GateDecision("pass", d, conf, is_teleport, **_diag)

        # --- VLM issued stop ---
        # Injection C: never veto the VLM's stop on a low-reliability distance
        # authority -- defer to the VLM instead (its stop is more trustworthy
        # than an untrusted gate distance). Recovers the ep680 vetoed-correct-
        # stops class; leaves the anchor-corroborated FORCE path (above) intact.
        if distance_authority_low_reliability:
            return GateDecision("deferred", d, conf, is_teleport, **_diag)

        if not high_conf:
            # Low confidence: normally defer to VLM entirely. Anchor
            # corroboration (see module docstring) is the one exception --
            # if the anchor currently tracked isn't itself a "close" one AND
            # this attempt's own (otherwise-untrusted) reading independently
            # says "far", that agreement is enough to veto without needing
            # confidence in this specific attempt's ICP quality. If the
            # anchor and the reading disagree (e.g. anchor says close but
            # the reading says far), that's a contradiction, not corroborated
            # evidence -- stay deferred rather than guess which one is right.
            if (
                self.anchor_corroboration_enabled
                and anchor_route_remaining is not None
                and anchor_route_remaining > self.r_in
                and d > self.r_out
            ):
                cmd = self._bearing_to_command(bearing_deg)
                return GateDecision(
                    "vetoed", d, conf, is_teleport,
                    suggested_command=cmd,
                    suggested_steps=10,
                    **_diag,
                )
            return GateDecision("deferred", d, conf, is_teleport, **_diag)

        if d <= self.r_in:
            # Inside arrival radius: accept
            return GateDecision("accepted", d, conf, is_teleport, **_diag)

        if d > self.r_out:
            # Beyond veto boundary: veto and inject forward command
            cmd = self._bearing_to_command(bearing_deg)
            return GateDecision(
                "vetoed", d, conf, is_teleport,
                suggested_command=cmd,
                suggested_steps=10,
                **_diag,
            )

        # Hysteresis zone (r_in < d ≤ r_out): defer to VLM
        return GateDecision("deferred", d, conf, is_teleport, **_diag)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_d_and_conf(self, progress) -> tuple:
        """Return (distance_to_start_m, confidence) from a RelativeStartProgress."""
        if progress is None:
            return None, 0.0

        d = getattr(progress, "distance_to_start_m", None)

        # Oracle sources always carry full confidence
        source: str = getattr(progress, "source", "") or ""
        if "oracle" in source or "direct_oracle" in source:
            return d, 1.0

        conf = getattr(progress, "relocalization_confidence", None)
        if conf is not None:
            return d, float(conf)

        # Estimate from filter std: σ=0 → conf=1, σ≥5m → conf=0
        std = getattr(progress, "filter_std_m", None)
        if std is not None:
            return d, max(0.0, 1.0 - float(std) / 5.0)

        # Source unknown → treat as low confidence
        return d, 0.0

    def _bearing_to_command(self, bearing_deg: Optional[float]) -> List[float]:
        """Return [vx, vy, vyaw] pointing toward bearing_deg.

        Positive bearing = start is to the robot's left → vyaw > 0 (turn left).
        """
        if bearing_deg is None:
            return [0.3, 0.0, 0.0]
        br = math.radians(float(bearing_deg))
        # Proportional yaw toward target, clamped
        vyaw = max(-0.4, min(0.4, br * 0.5))
        # Reduce forward speed when turning hard
        vx = 0.3 if abs(bearing_deg) < 60.0 else 0.15
        return [vx, 0.0, vyaw]
