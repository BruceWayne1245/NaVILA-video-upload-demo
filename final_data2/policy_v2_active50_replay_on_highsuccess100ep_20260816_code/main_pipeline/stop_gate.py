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
  BLIND_BUDGET_EXHAUSTED  (2026-08-04, opt-in via blind_budget_enabled) would
            otherwise be DEFERRED via distance_authority_low_reliability, but
            blind_streak consecutive such attempts already happened without a
            trustworthy reading in between → treated like VETOED (suppress,
            inject movement) instead of trusting the unverified VLM claim yet
            again. See blind_budget_enabled's docstring in __init__.

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
    decision: str                         # "pass"|"accepted"|"vetoed"|"forced"|"deferred"|"blind_budget_exhausted"
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
    # 2026-08-04 (frozen-relocalization-reading fix): see
    # RelativeStartProgress.relocalization_stale_attempts' docstring in
    # route_memory_agent.py. Purely observational unless
    # sequential_pair_stale_relocalization_distrust is on, in which case a
    # high value here explains a "deferred" decision that would otherwise
    # look identical to Injection C's own low-reliability defer.
    relocalization_stale_attempts: Optional[int] = None
    # 2026-08-04 (blind-budget fix, borrows Route2's "positive terminal
    # evidence only" principle -- investigations/2026-07-28-anchor-support-
    # recovery et al.): consecutive real attempts (d is not None, not a
    # teleport frame) where distance_authority_low_reliability was true --
    # i.e. we currently have NO trustworthy distance authority at all,
    # regardless of whether the VLM has proposed a stop. See
    # blind_budget_enabled's docstring for what happens once this exceeds
    # blind_budget_max_attempts.
    blind_streak: Optional[int] = None
    # 2026-08-04 (growing-uncertainty variant of the staleness fix, see
    # RelativeStartProgress.distance_uncertainty_radius_m's docstring in
    # route_memory_agent.py). Purely observational unless
    # use_uncertainty_interval is on, in which case it explains why an
    # otherwise-in-range d didn't get accepted/vetoed (interval straddled
    # the boundary) despite looking unambiguous as a point value.
    distance_uncertainty_radius_m: Optional[float] = None
    # 2026-08-04 (cross-role agreement). See
    # RelativeStartProgress.cross_role_distance_to_start_m's docstring in
    # route_memory_agent.py. Purely observational unless
    # require_cross_role_agreement is on, in which case it explains why an
    # otherwise-in-range FORCE/ACCEPTED instead landed on pass/deferred.
    cross_role_distance_to_start_m: Optional[float] = None

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
            "gate_relocalization_stale_attempts": self.relocalization_stale_attempts,
            "gate_blind_streak": self.blind_streak,
            "gate_distance_uncertainty_radius_m": self.distance_uncertainty_radius_m,
            "gate_cross_role_distance_to_start_m": self.cross_role_distance_to_start_m,
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
        # 2026-08-04 (Mechanism D fix, investigations/2026-07-28-downgrade-
        # batch-mechanism-failure-classification/FINDINGS.md): off by default,
        # byte-identical prior behavior. See the flag's use-site in check()
        # for why this was needed -- anchor-corroboration's veto is designed
        # to be trusted independent of this attempt's own live-reading
        # quality (FORCE's own anchor_forces already ignores it entirely),
        # but the low-reliability defer below returned unconditionally before
        # corroboration's veto check ever ran, silently disabling that safety
        # net whenever Injection C also flagged the same reading.
        corroboration_overrides_low_reliability: bool = False,
        # 2026-08-04 (blind-budget fix): off by default, byte-identical prior
        # behavior. investigations/2026-07-28-anchor-support-recovery's
        # independent stop-decision redesign (a separate Route2 branch, not
        # this file) identified the same root problem this targets: a
        # low-reliability/stale "deferred" is, in effect, an UNCONDITIONAL
        # accept of whatever the VLM proposed -- there is no limit on how
        # many consecutive times that can happen. Confirmed as a real,
        # non-hypothetical cost on this project's own data (investigations/
        # 2026-08-01-anchor0-fix-and-quarantine-veto/FINDINGS.md): the same
        # false "I'm home" VLM claim was correctly vetoed once at high
        # confidence, then let through later purely because confidence
        # happened to read low that attempt. When on, once blind_streak (see
        # GateDecision.blind_streak's docstring) exceeds
        # blind_budget_max_attempts, an otherwise-"deferred" VLM-issued-stop
        # decision becomes "blind_budget_exhausted" instead (round_trip_
        # eval.py treats it identically to "vetoed": inject a movement
        # command, don't accept the stop) -- we stop trusting an unverified
        # VLM claim once we've had no independent way to check it for this
        # long, falling back to "keep moving" rather than "keep blindly
        # trusting." Does NOT end the episode outright (this file has no way
        # to do that -- see the flag's own follow-up note in this session for
        # why a genuine early-failure hook was deliberately left for a
        # separate, explicitly-reviewed change to round_trip_eval.py's main
        # loop instead of being bundled in here).
        blind_budget_enabled: bool = False,
        blind_budget_max_attempts: int = 8,
        # 2026-08-04 (growing-uncertainty variant). Off by default, byte-
        # identical prior behavior: accept/veto still compare the point
        # distance d directly. When on and progress carries a
        # distance_uncertainty_radius_m (route_memory_agent.py's
        # sequential_pair_relocalization_uncertainty_mode="growing"),
        # accept requires the WORST case (d + radius) still <= r_in and veto
        # requires the BEST case (d - radius) still > r_out -- an interval
        # that straddles either boundary falls through to deferred instead
        # of a point comparison confidently picking a side under growing
        # doubt. FORCE and the not-high_conf/anchor_corroboration branch are
        # deliberately untouched -- FORCE already has its own multi-attempt
        # confirm-streak robustness, and corroboration's veto is explicitly
        # designed to not depend on this attempt's own reading quality at
        # all (see class docstring), so widening ITS distance term by this
        # same radius would work against its own stated purpose.
        use_uncertainty_interval: bool = False,
        # 2026-08-04 (cross-role agreement). Off by default, byte-identical
        # prior behavior. current and next roles' ICP matches are against
        # DIFFERENT anchors' point clouds -- a genuine independent cross-
        # check, unlike anchor-corroboration's own reuse of this same
        # reading (which is exactly why ep93/581/427/669's "confidently
        # wrong" false-FORCE class kept recurring: an entire downstream
        # anchor chain can get confidently-wrong-matched at once, so
        # anchor_route_remaining and d end up being the SAME poisoned
        # identity agreeing with itself, not two independent signals). When
        # on, FORCE and ACCEPTED both additionally require the OTHER role's
        # own independently-derived distance (RelativeStartProgress.
        # cross_role_distance_to_start_m) to be within
        # cross_role_max_disagreement_m of d -- missing data (that role
        # currently has no estimate) is treated as "cannot verify," not
        # "disagrees," and does not block.
        require_cross_role_agreement: bool = False,
        cross_role_max_disagreement_m: float = 1.5,
        # 2026-08-15 (this session's Bucket-2/17-episode investigation on
        # line2_closure_off_cooldown_kdtree_100ep_20260815): off by default,
        # byte-identical prior behavior. Root cause found: relocalization
        # confidence oscillates within a single episode's final approach
        # (observed swinging 1.0 -> 0.2 -> 0.8 across consecutive VLM-query
        # attempts on ep688/815/783/784/785), and both `high_conf` here and
        # `distance_authority_low_reliability` (set upstream by route_memory_
        # agent) are single-attempt judgments -- a single unlucky low-
        # confidence reading is enough to defer/blind-budget-exhaust a VLM
        # stop that arrived on a genuinely-converged, repeatedly-corroborated
        # distance estimate. Mirrors route_memory_agent.py's own
        # _promotion_trend_improving (same project, same fix shape, already
        # validated there for a different decision) applied here for the
        # first time: when this attempt's own single-reading trust check
        # would otherwise fail, a rolling window of recent (d, conf) readings
        # can still grant trust if enough of them were independently
        # high-confidence AND this attempt's own d is consistent with what
        # those trusted readings showed (guards against "confidence was good
        # a while ago but the estimate has since drifted" -- not just
        # majority-vote-on-confidence-alone). See _trend_confidence_trusts's
        # docstring for the exact rule.
        trend_confidence_enabled: bool = False,
        trend_confidence_window: int = 5,
        trend_confidence_min_samples: int = 3,
        trend_confidence_min_high_conf_votes: int = 3,
        trend_confidence_max_distance_spread_m: float = 1.0,
        # 2026-08-15 (same investigation, follow-up after trend_confidence
        # above was offline-replayed against real ep688/815/783/784/785 data
        # and found to fire 0/5 times there -- not because it doesn't work
        # (it does: 67/297 = 22.6% of low-confidence attempts across a wider
        # 13-episode sample DID get trend-corroborated), but because the real
        # blocker at those specific VLM-stop moments turned out to be
        # something else entirely: require_cross_role_agreement, where
        # current's and next's independently-derived distance estimates
        # disagreed by 1.7-6.5m -- ALL 5 of the 5 VLM-issued-stop attempts
        # across those episodes were blocked there, none by confidence. Off
        # by default, byte-identical prior behavior. Same fix shape as
        # trend_confidence: a single attempt's cross-role gap can be a
        # transient artifact of one side's ICP noise even when the two roles
        # have mostly agreed recently -- a rolling window of past gaps can
        # grant trust when this attempt's own gap is the outlier, not the
        # trend.
        cross_role_trend_enabled: bool = False,
        cross_role_trend_window: int = 5,
        cross_role_trend_min_samples: int = 3,
    ) -> None:
        if r_in > r_out:
            raise ValueError(f"r_in ({r_in}) must be ≤ r_out ({r_out})")
        self.r_in = float(r_in)
        self.r_out = float(r_out)
        self.confirm_steps = int(confirm_steps)
        self.min_confidence = float(min_confidence)
        self.anchor_corroboration_enabled = bool(anchor_corroboration_enabled)
        self.forced_stop_anchor_confirm_steps = int(forced_stop_anchor_confirm_steps)
        self.corroboration_overrides_low_reliability = bool(corroboration_overrides_low_reliability)
        self.blind_budget_enabled = bool(blind_budget_enabled)
        self.blind_budget_max_attempts = int(blind_budget_max_attempts)
        self.use_uncertainty_interval = bool(use_uncertainty_interval)
        self.require_cross_role_agreement = bool(require_cross_role_agreement)
        self.cross_role_max_disagreement_m = float(cross_role_max_disagreement_m)
        self.trend_confidence_enabled = bool(trend_confidence_enabled)
        self.trend_confidence_window = int(trend_confidence_window)
        self.trend_confidence_min_samples = int(trend_confidence_min_samples)
        self.trend_confidence_min_high_conf_votes = int(trend_confidence_min_high_conf_votes)
        self.trend_confidence_max_distance_spread_m = float(trend_confidence_max_distance_spread_m)
        self.cross_role_trend_enabled = bool(cross_role_trend_enabled)
        self.cross_role_trend_window = int(cross_role_trend_window)
        self.cross_role_trend_min_samples = int(cross_role_trend_min_samples)

        self._confirm_count: int = 0
        self._anchor_close_streak: int = 0
        self._blind_streak: int = 0
        self._prev_sim_pos: Optional[List[float]] = None  # [x, y]
        self._teleport_pending: bool = False
        self._trend_history: List[tuple] = []  # [(d, conf), ...], most recent last
        self._cross_role_gap_history: List[float] = []  # abs(d - cross_role_d), most recent last
        self.last_high_conf: Optional[bool] = None       # diagnostic only, see check()
        self.last_trend_override_fired: bool = False      # diagnostic only, see check()
        self.last_cross_role_trend_override_fired: bool = False  # diagnostic only, see _cross_role_agrees()

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
        relocalization_stale_attempts: Optional[int] = getattr(
            progress, "relocalization_stale_attempts", None
        )
        distance_uncertainty_radius_m: Optional[float] = getattr(
            progress, "distance_uncertainty_radius_m", None
        )
        cross_role_distance_to_start_m: Optional[float] = getattr(
            progress, "cross_role_distance_to_start_m", None
        )
        _diag = dict(
            anchor_progress_role=anchor_progress_role,
            anchor_index=anchor_idx,
            anchor_route_remaining=anchor_route_remaining,
            current_anchor_index=current_anchor_idx,
            current_anchor_unreliable=current_anchor_unreliable,
            current_evict_streak=current_evict_streak,
            relocalization_stale_attempts=relocalization_stale_attempts,
            blind_streak=self._blind_streak,
            distance_uncertainty_radius_m=distance_uncertainty_radius_m,
            cross_role_distance_to_start_m=cross_role_distance_to_start_m,
        )

        # No authoritative distance → cannot arbitrate
        if d is None:
            self._confirm_count = 0
            self._anchor_close_streak = 0
            self._blind_streak = 0
            _diag["blind_streak"] = 0
            return GateDecision("pass", None, conf if conf else 0.0, is_teleport, **_diag)

        # Teleport frame: don't count toward arrival, don't arbitrate
        if is_teleport:
            return GateDecision("pass", d, conf, is_teleport, **_diag)

        high_conf = conf >= self.min_confidence

        # 2026-08-15 (cross-role trend fix, see cross_role_trend_enabled's
        # docstring at __init__): record this attempt's cross-role gap
        # unconditionally, every real (non-None, non-teleport) attempt --
        # deliberately NOT inside _cross_role_agrees() itself, since that is
        # only ever called from the FORCE/ACCEPTED branches once several
        # OTHER conditions already hold, which would make the window sparse
        # and skewed toward already-promising attempts instead of a genuine
        # recent history.
        if self.cross_role_trend_enabled and cross_role_distance_to_start_m is not None:
            self._cross_role_gap_history.append(abs(d - cross_role_distance_to_start_m))
            if len(self._cross_role_gap_history) > self.cross_role_trend_window:
                del self._cross_role_gap_history[: len(self._cross_role_gap_history) - self.cross_role_trend_window]

        # 2026-08-15 (trend-confidence fix, see trend_confidence_enabled's
        # docstring at __init__): record this attempt in the rolling window
        # BEFORE deciding whether to grant trend-based trust, so a single
        # attempt can never vote for its own trust using only itself. When
        # this attempt's own single-reading checks would otherwise withhold
        # trust (low confidence and/or route-memory's own low-reliability
        # flag), a sufficiently corroborated recent trend can still grant it.
        # Deliberately does NOT touch _confirm_count/_blind_streak/
        # _anchor_close_streak's own update logic below -- those still see
        # whatever high_conf/distance_authority_low_reliability end up being
        # after this override, exactly as they always have.
        if self.trend_confidence_enabled:
            self._trend_history.append((d, conf))
            if len(self._trend_history) > self.trend_confidence_window:
                del self._trend_history[: len(self._trend_history) - self.trend_confidence_window]
            if not high_conf or distance_authority_low_reliability:
                if self._trend_confidence_trusts(d):
                    high_conf = True
                    distance_authority_low_reliability = False
                    self.last_trend_override_fired = True
                else:
                    self.last_trend_override_fired = False
            else:
                self.last_trend_override_fired = False
        else:
            self.last_trend_override_fired = False
        # Diagnostic only (2026-08-15), never read by any decision logic --
        # lets offline replay/tests inspect the actual post-override value
        # instead of inferring it from the returned decision label, which is
        # ambiguous (e.g. "deferred" can happen at high_conf==True too, via
        # the hysteresis zone or cross_role_agreement).
        self.last_high_conf = high_conf

        # 2026-08-04 (blind-budget fix): consecutive real attempts with no
        # trustworthy distance authority, tracked regardless of
        # vlm_issued_stop (see GateDecision.blind_streak's docstring) --
        # deliberately keyed to distance_authority_low_reliability alone, not
        # `not high_conf` in general: that weaker condition already has its
        # own mitigation below (anchor_corroboration's veto) and is a
        # meaningfully different, more common regime ("somewhat uncertain",
        # not "no information at all").
        if distance_authority_low_reliability:
            self._blind_streak += 1
        else:
            self._blind_streak = 0
        _diag["blind_streak"] = self._blind_streak

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
        if (
            not vlm_issued_stop
            and ((high_conf and self._confirm_count >= self.confirm_steps) or anchor_forces)
            and self._cross_role_agrees(d, cross_role_distance_to_start_m)
        ):
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
            # 2026-08-04 (Mechanism D fix): let corroboration's veto go first
            # when enabled -- it explicitly does not depend on this attempt's
            # own reading quality (see class docstring), so Injection C
            # flagging that same reading low-reliability is not a reason to
            # skip it. Root cause of ep205: d=10.76m, anchor's own remaining
            # =7.05m -- both corroboration conditions satisfied, but this
            # branch fired first and deferred anyway before the flag existed.
            if (
                self.corroboration_overrides_low_reliability
                and self.anchor_corroboration_enabled
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
            # 2026-08-04 (blind-budget fix): a "deferred" here is, in effect,
            # an unconditional accept of whatever the VLM proposed -- bound
            # how many consecutive times that can happen. Once exhausted,
            # stop trusting the unverified claim and fall back to "keep
            # moving" (reuses the same suggested_command machinery "vetoed"
            # already uses) rather than "keep blindly trusting."
            if self.blind_budget_enabled and self._blind_streak > self.blind_budget_max_attempts:
                cmd = self._bearing_to_command(bearing_deg)
                return GateDecision(
                    "blind_budget_exhausted", d, conf, is_teleport,
                    suggested_command=cmd,
                    suggested_steps=10,
                    **_diag,
                )
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

        # 2026-08-04 (growing-uncertainty variant): widen the boundary checks
        # by the reported radius when present -- see use_uncertainty_interval's
        # docstring. radius is always None or >= 0.0 (route_memory_agent.py
        # never emits a negative one), so accepted_bound/vetoed_bound
        # collapse to plain d when the interval isn't active, byte-identical
        # to the point-comparison behavior below.
        radius = (
            distance_uncertainty_radius_m
            if self.use_uncertainty_interval and distance_uncertainty_radius_m is not None
            else 0.0
        )
        accepted_bound = d + radius   # worst case still has to clear r_in
        vetoed_bound = d - radius     # best case still has to clear r_out

        if accepted_bound <= self.r_in and self._cross_role_agrees(d, cross_role_distance_to_start_m):
            # Inside arrival radius (even in the worst case under
            # uncertainty), and the other role's own independent estimate
            # doesn't disagree: accept
            return GateDecision("accepted", d, conf, is_teleport, **_diag)

        if vetoed_bound > self.r_out:
            # Beyond veto boundary (even in the best case under
            # uncertainty): veto and inject forward command
            cmd = self._bearing_to_command(bearing_deg)
            return GateDecision(
                "vetoed", d, conf, is_teleport,
                suggested_command=cmd,
                suggested_steps=10,
                **_diag,
            )

        # Hysteresis zone (r_in < d ≤ r_out), or -- when the interval is
        # active -- genuinely ambiguous under uncertainty either way: defer
        # to VLM (subject to the blind-budget above on a future attempt).
        return GateDecision("deferred", d, conf, is_teleport, **_diag)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cross_role_agrees(self, d: float, cross_role_distance_to_start_m: Optional[float]) -> bool:
        """True unless require_cross_role_agreement is on AND the other
        role's own independent distance estimate disagrees with d by more
        than cross_role_max_disagreement_m. Missing data (the other role has
        no current estimate) is "cannot verify," not "disagrees" -- see
        require_cross_role_agreement's docstring in __init__.

        2026-08-15: when this attempt's own gap fails that single-reading
        check, cross_role_trend_enabled can still grant trust if at least
        cross_role_trend_min_samples of the OTHER readings in the recent
        window independently agreed (their own gap already <=
        cross_role_max_disagreement_m on their own terms) -- this attempt's
        large gap is then a one-off outlier (one side's ICP noise for this
        one attempt), not evidence the two roles have genuinely diverged.
        Deliberately counts only already-agreeing readings toward the vote
        (mirrors _trend_confidence_trusts's min_high_conf_votes, not a plain
        len(window) count) -- a window that's mostly this same large gap
        repeated must not satisfy its own corroboration requirement just by
        being long enough."""
        if not self.require_cross_role_agreement:
            self.last_cross_role_trend_override_fired = False
            return True
        if cross_role_distance_to_start_m is None:
            self.last_cross_role_trend_override_fired = False
            return True
        gap = abs(d - cross_role_distance_to_start_m)
        if gap <= self.cross_role_max_disagreement_m:
            self.last_cross_role_trend_override_fired = False
            return True
        if self.cross_role_trend_enabled:
            window = self._cross_role_gap_history[-self.cross_role_trend_window:]
            agreeing = [g for g in window if g <= self.cross_role_max_disagreement_m]
            if len(agreeing) >= self.cross_role_trend_min_samples:
                self.last_cross_role_trend_override_fired = True
                return True
        self.last_cross_role_trend_override_fired = False
        return False

    def _trend_confidence_trusts(self, d: float) -> bool:
        """2026-08-15: True when a rolling window of recent (d, conf)
        readings corroborates trusting THIS attempt's distance, even though
        its own single-reading confidence/reliability check just failed.
        Two conditions, both required:
          1. At least trend_confidence_min_high_conf_votes of the last
             trend_confidence_window readings independently cleared
             min_confidence on their own -- a majority-of-recent-looks
             signal, not just "was ever confident once."
          2. This attempt's own d is within trend_confidence_max_distance_
             spread_m of the MEDIAN d among those high-confidence readings --
             guards against trusting a stale trend that has since drifted
             (e.g. confidence was good several attempts ago at d=8m, this
             attempt reports d=2m at low confidence -- that is a suspicious
             jump, not corroboration, and must not be trusted just because
             older readings were confident).
        Requires at least trend_confidence_min_samples readings in the
        window at all before considering trust (an near-empty history can't
        corroborate anything)."""
        if d is None or len(self._trend_history) < self.trend_confidence_min_samples:
            return False
        window = self._trend_history[-self.trend_confidence_window:]
        trusted_ds = sorted(hd for hd, hc in window if hc >= self.min_confidence)
        if len(trusted_ds) < self.trend_confidence_min_high_conf_votes:
            return False
        median_trusted_d = trusted_ds[len(trusted_ds) // 2]
        return abs(d - median_trusted_d) <= self.trend_confidence_max_distance_spread_m

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
