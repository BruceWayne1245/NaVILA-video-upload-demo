"""Deterministic, VLM-free return controller for the NaVILA M50 ablation.

The controller follows the outbound dead-reckoned breadcrumb polyline in
reverse.  It deliberately consumes only route-relative pose geometry; it does
not inspect simulator world poses, RGB, language, or reliability scores.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Optional, Sequence

import numpy as np


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


@dataclass(frozen=True)
class PathFollowingConfig:
    lookahead_m: float = 0.65
    turn_enter_deg: float = 28.0
    turn_exit_deg: float = 12.0
    stop_distance_m: float = 0.35
    forward_speed_mps: float = 0.5
    turn_speed_radps: float = math.pi / 6.0
    command_duration_s: float = 0.5
    projection_window_m: float = 3.0
    allow_stop: bool = True


@dataclass(frozen=True)
class PathFollowingDecision:
    kind: str
    command: tuple[float, float, float]
    duration_seconds: float
    bearing_deg: float
    distance_to_target_m: float
    projected_s_m: float
    target_s_m: float
    distance_to_start_m: float
    cross_track_error_m: float
    reason: str

    def as_log_dict(self) -> dict:
        data = asdict(self)
        data["command"] = list(self.command)
        return data


class DeterministicPathFollower:
    """Reverse-polyline tracker with a stateful turn hysteresis.

    ``path`` is in outbound order and in the route-memory start frame.
    ``pose`` is ``[x, y, yaw]`` in that same frame.  Arc length ``s=0`` is the
    outbound start, so return progress is monotonically decreasing ``s``.
    """

    def __init__(self, config: Optional[PathFollowingConfig] = None):
        self.cfg = config or PathFollowingConfig()
        self._turning = False
        self._last_projected_s_m: Optional[float] = None

    def reset(self) -> None:
        self._turning = False
        self._last_projected_s_m = None

    @staticmethod
    def _prepare_path(path: Iterable[Sequence[float]]) -> np.ndarray:
        points = np.asarray([[float(p[0]), float(p[1])] for p in path], dtype=np.float64)
        if len(points) < 2:
            raise ValueError("path follower needs at least two breadcrumb points")
        keep = np.ones(len(points), dtype=bool)
        keep[1:] = np.linalg.norm(points[1:] - points[:-1], axis=1) > 1e-6
        points = points[keep]
        if len(points) < 2:
            raise ValueError("path follower needs two distinct breadcrumb points")
        return points

    @staticmethod
    def _arc_lengths(points: np.ndarray) -> np.ndarray:
        lengths = np.linalg.norm(points[1:] - points[:-1], axis=1)
        return np.concatenate(([0.0], np.cumsum(lengths)))

    @staticmethod
    def _point_at_s(points: np.ndarray, arc: np.ndarray, s_m: float) -> np.ndarray:
        s_m = float(np.clip(s_m, 0.0, arc[-1]))
        index = min(int(np.searchsorted(arc, s_m, side="right") - 1), len(points) - 2)
        span = float(arc[index + 1] - arc[index])
        t = 0.0 if span <= 1e-9 else (s_m - float(arc[index])) / span
        return points[index] + t * (points[index + 1] - points[index])

    def _project(self, points: np.ndarray, arc: np.ndarray, xy: np.ndarray) -> tuple[float, float]:
        best: Optional[tuple[float, float]] = None
        for index, (a, b) in enumerate(zip(points[:-1], points[1:])):
            seg_lo = float(arc[index])
            seg_hi = float(arc[index + 1])
            if self._last_projected_s_m is not None:
                lo = max(0.0, self._last_projected_s_m - self.cfg.projection_window_m)
                hi = min(float(arc[-1]), self._last_projected_s_m + 0.5)
                if seg_hi < lo or seg_lo > hi:
                    continue
            delta = b - a
            denom = float(np.dot(delta, delta))
            t = 0.0 if denom <= 1e-12 else float(np.clip(np.dot(xy - a, delta) / denom, 0.0, 1.0))
            projected = a + t * delta
            error = float(np.linalg.norm(xy - projected))
            s_m = seg_lo + t * (seg_hi - seg_lo)
            candidate = (error, s_m)
            if best is None or candidate < best:
                best = candidate
        if best is None:
            raise RuntimeError("no path segment inside projection window")
        return best[1], best[0]

    def decide(
        self,
        path: Iterable[Sequence[float]],
        pose_from_start: Sequence[float],
        distance_to_start_m: Optional[float] = None,
    ) -> PathFollowingDecision:
        points = self._prepare_path(path)
        arc = self._arc_lengths(points)
        pose = np.asarray([float(v) for v in pose_from_start[:3]], dtype=np.float64)
        projected_s_m, cross_track_error_m = self._project(points, arc, pose[:2])
        if self._last_projected_s_m is not None:
            # Return progress may jitter slightly backwards, but cannot jump far
            # toward the outbound goal because of an ambiguous nearest segment.
            projected_s_m = min(projected_s_m, self._last_projected_s_m + 0.25)
        self._last_projected_s_m = projected_s_m

        geometric_start_distance = float(np.linalg.norm(pose[:2] - points[0]))
        start_distance = (
            geometric_start_distance
            if distance_to_start_m is None
            else float(distance_to_start_m)
        )
        target_s_m = max(0.0, projected_s_m - self.cfg.lookahead_m)
        target = self._point_at_s(points, arc, target_s_m)
        delta_world = target - pose[:2]
        c, s = math.cos(float(pose[2])), math.sin(float(pose[2]))
        dx_body = c * float(delta_world[0]) + s * float(delta_world[1])
        dy_body = -s * float(delta_world[0]) + c * float(delta_world[1])
        target_distance = math.hypot(dx_body, dy_body)
        bearing_deg = math.degrees(math.atan2(dy_body, dx_body)) if target_distance > 1e-9 else 0.0

        if self.cfg.allow_stop and start_distance <= self.cfg.stop_distance_m and target_s_m <= 1e-6:
            self._turning = False
            kind, command, duration, reason = "stop", (0.0, 0.0, 0.0), 0.0, "route_start_reached"
        else:
            threshold = self.cfg.turn_exit_deg if self._turning else self.cfg.turn_enter_deg
            self._turning = abs(bearing_deg) > threshold
            if self._turning:
                sign = 1.0 if bearing_deg > 0.0 else -1.0
                kind = "turn_left" if sign > 0.0 else "turn_right"
                command = (0.0, 0.0, sign * self.cfg.turn_speed_radps)
                duration = self.cfg.command_duration_s
                reason = "align_to_reverse_route"
            else:
                kind = "forward"
                command = (self.cfg.forward_speed_mps, 0.0, 0.0)
                duration = self.cfg.command_duration_s
                reason = "track_reverse_route"

        return PathFollowingDecision(
            kind=kind,
            command=command,
            duration_seconds=float(duration),
            bearing_deg=float(bearing_deg),
            distance_to_target_m=float(target_distance),
            projected_s_m=float(projected_s_m),
            target_s_m=float(target_s_m),
            distance_to_start_m=float(start_distance),
            cross_track_error_m=float(cross_track_error_m),
            reason=reason,
        )
