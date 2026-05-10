"""Pure trajectory policy evaluator for the synthetic RDS benchmark suite.

This module is intentionally free of rich/console dependencies so it can be
imported and unit-tested without pulling in the full observation rendering stack.

The three public symbols are re-exported from observations.py for backward
compatibility with existing import sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.synthetic.rds_postgres.observations import TrajectoryMetrics


@dataclass(frozen=True)
class TrajectoryPolicy:
    """Constraints applied to the agent's execution trajectory.

    Attributes:
        matching: Comparison mode — one of ``"strict"``, ``"lcs"``, ``"set"``.
        max_edit_distance: Maximum allowed Levenshtein distance from golden trajectory.
        max_extra_actions: Maximum allowed actions beyond the golden set.
        max_redundancy: Maximum allowed repeated actions.
        max_loops: Maximum allowed investigation loops.
    """

    matching: str
    max_edit_distance: int | None = None
    max_extra_actions: int | None = None
    max_redundancy: int | None = None
    max_loops: int | None = None


@dataclass(frozen=True)
class TrajectoryPolicyResult:
    """Outcome of evaluating a trajectory against a policy.

    Attributes:
        passed: True when no violations were detected.
        matching: The matching mode that was evaluated.
        violations: Human-readable violation descriptions (empty when passed).
    """

    passed: bool
    matching: str
    violations: list[str]


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "None"
    return f"{value:.2f}"


def evaluate_trajectory_policy(
    metrics: TrajectoryMetrics,
    golden_actions: list[str],
    policy: TrajectoryPolicy | None,
) -> TrajectoryPolicyResult | None:
    """Evaluate *metrics* against *policy* and return a result.

    Returns ``None`` when there is no golden trajectory or policy to check
    (the caller records this as a ``not_applicable`` gate).

    Args:
        metrics: Computed trajectory metrics from ``compute_trajectory_metrics``.
        golden_actions: The expected action sequence from the fixture answer key.
        policy: The policy constraints to enforce.  When ``None``, returns ``None``.

    Returns:
        ``TrajectoryPolicyResult`` with ``passed=True`` if no violations, or
        ``None`` when the check is not applicable.
    """
    if not golden_actions or policy is None:
        return None

    violations: list[str] = []
    matching = policy.matching

    if matching == "strict" and metrics.strict_match is not True:
        violations.append("strict sequence mismatch")
    elif matching == "lcs" and metrics.lcs_ratio != 1.0:
        violations.append(f"lcs_ratio={_fmt_ratio(metrics.lcs_ratio)} < 1.00")
    elif matching == "set" and metrics.missing_actions:
        violations.append(f"missing actions: {', '.join(metrics.missing_actions)}")

    if (
        policy.max_edit_distance is not None
        and metrics.edit_distance is not None
        and metrics.edit_distance > policy.max_edit_distance
    ):
        violations.append(f"edit_distance={metrics.edit_distance} > {policy.max_edit_distance}")
    if policy.max_extra_actions is not None:
        extra_count = len(metrics.extra_actions)
        if extra_count > policy.max_extra_actions:
            violations.append(f"extra_actions={extra_count} > {policy.max_extra_actions}")
    if policy.max_redundancy is not None and metrics.redundancy_count > policy.max_redundancy:
        violations.append(f"redundancy_count={metrics.redundancy_count} > {policy.max_redundancy}")
    if policy.max_loops is not None and metrics.loops_used > policy.max_loops:
        violations.append(f"loops_used={metrics.loops_used} > {policy.max_loops}")

    return TrajectoryPolicyResult(
        passed=not violations,
        matching=matching,
        violations=violations,
    )
