from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NavigationSafetyConfig:
    odometry_timeout: float = 0.5
    path_timeout: float = 2.0


class NavigationSafetyPolicy:
    """
    Fail-closed safety policy for navigation command generation.

    This does not replace a hardware emergency stop.
    """

    def __init__(
        self,
        config: NavigationSafetyConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or NavigationSafetyConfig()
        self.clock = clock

        if (
            not math.isfinite(self.config.odometry_timeout)
            or self.config.odometry_timeout <= 0
            or not math.isfinite(self.config.path_timeout)
            or self.config.path_timeout <= 0
        ):
            raise ValueError("Timeouts must be positive and finite")

        self.enabled = False
        self.last_odom: float | None = None
        self.last_path: float | None = None
        self.pose_valid = False
        self.path_valid = False

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def update_odometry(
        self,
        x: float,
        y: float,
        yaw: float,
    ) -> bool:
        self.pose_valid = all(
            math.isfinite(v) for v in (x, y, yaw)
        )

        self.last_odom = (
            self.clock() if self.pose_valid else None
        )

        return self.pose_valid

    def update_path(
        self,
        points: list[tuple[float, float]],
        path_frame: str,
        odom_frame: str,
    ) -> bool:
        self.path_valid = (
            bool(points)
            and path_frame == odom_frame
            and bool(path_frame)
            and all(
                len(point) == 2
                and all(math.isfinite(v) for v in point)
                for point in points
            )
        )

        self.last_path = (
            self.clock() if self.path_valid else None
        )

        return self.path_valid

    def can_move(self) -> bool:
        if not self.enabled:
            return False

        if not self.pose_valid or not self.path_valid:
            return False

        now = self.clock()

        if self.last_odom is None or self.last_path is None:
            return False

        if (
            now - self.last_odom < 0
            or now - self.last_odom > self.config.odometry_timeout
        ):
            return False

        if (
            now - self.last_path < 0
            or now - self.last_path > self.config.path_timeout
        ):
            return False

        return True