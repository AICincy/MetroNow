"""Process-local fail-open visibility counter.

Several read-only feeds (Notes, Osmose, Transit, MOTIS) intentionally
swallow HTTP errors and return empty data so a transient upstream
problem doesn't block a scan. That's the right policy — but it makes
"feed is down" indistinguishable from "no findings exist" in the
summary. This module records a lightweight tally of every fail-open
event that occurs during a single CLI invocation so the user can be
told at the end "Osmose: 1 transient timeout during scan", instead
of silently consuming a degraded result.

Design notes:

* **Process-local, not persistent.** A scan is one-shot; cross-process
  aggregation would need IPC. If you need durability, the underlying
  module already logs the error; this is purely a UX layer.

* **No typed-error hierarchy.** Each call records ``(feed, reason)``
  tuples and one optional short detail. Reason strings are an open
  vocabulary to keep call sites trivial; representative values are
  ``"timeout"``, ``"http_error"``, ``"network"``, ``"non_json"``,
  ``"rate_limit"``, ``"unknown"``.

* **Reset between independent runs.** The CLI calls :func:`reset` at
  the start of each command so previous-run noise doesn't leak.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class _Counter:
    by_feed: Counter[str] = field(default_factory=Counter)
    by_pair: Counter[tuple[str, str]] = field(default_factory=Counter)
    samples: list[tuple[str, str, str]] = field(default_factory=list)


_state = _Counter()
# Cap stored detail samples to avoid runaway memory on a long-running
# server; the first few are the most informative.
_MAX_SAMPLES_PER_PAIR = 3


def record(feed: str, reason: str, detail: str = "") -> None:
    """Log one fail-open event. Cheap; safe to call inside hot paths."""
    _state.by_feed[feed] += 1
    _state.by_pair[(feed, reason)] += 1
    pair_count = sum(
        1 for f, r, _ in _state.samples if f == feed and r == reason
    )
    if detail and pair_count < _MAX_SAMPLES_PER_PAIR:
        _state.samples.append((feed, reason, detail[:200]))


def reset() -> None:
    """Clear the counter — call at the start of each CLI run."""
    _state.by_feed.clear()
    _state.by_pair.clear()
    _state.samples.clear()


def total() -> int:
    return int(sum(_state.by_feed.values()))


def summary() -> dict:
    """Structured snapshot for CLI / report consumers."""
    return {
        "total": total(),
        "by_feed": dict(_state.by_feed),
        "by_pair": [
            {"feed": f, "reason": r, "count": c}
            for (f, r), c in _state.by_pair.most_common()
        ],
        "samples": [
            {"feed": f, "reason": r, "detail": d}
            for f, r, d in _state.samples
        ],
    }


def format_human() -> str:
    """One-line-per-pair human summary; empty string if nothing recorded."""
    if total() == 0:
        return ""
    lines = [f"⚠ {total()} transient feed error(s) during this run:"]
    for (feed, reason), count in _state.by_pair.most_common():
        lines.append(f"  {feed}: {count} × {reason}")
    return "\n".join(lines)
