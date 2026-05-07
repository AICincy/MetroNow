"""Node disconnect detection: haversine endpoint distances + spatial clustering."""

from __future__ import annotations

from .config import GAP_CLUSTER_M, GAP_THRESHOLD_M
from .geo import haversine_m


def detect_gaps(class_b_streets: dict[str, list[dict]]) -> list[dict]:
    """Find probable node disconnects among multi-segment streets.

    For each Class B street, enumerate all way-pairs and compute the minimum
    great-circle endpoint distance.  Pairs in (0.01 m, GAP_THRESHOLD_M] are
    emitted as candidates, then spatially clustered per street at
    GAP_CLUSTER_M so a k-way junction counts once, not k*(k-1)/2 times.
    """
    gaps: list[dict] = []
    for street, ways in class_b_streets.items():
        endpoints: list[tuple[dict, list[float], list[float]]] = []
        for w in ways:
            if len(w["geometry"]) >= 2:
                endpoints.append((w, w["geometry"][0], w["geometry"][-1]))

        raw_gaps_for_street: list[dict] = []
        for i in range(len(endpoints)):
            wi, si, ei = endpoints[i]
            for j in range(i + 1, len(endpoints)):
                wj, sj, ej = endpoints[j]
                pairs = [(si, sj), (si, ej), (ei, sj), (ei, ej)]
                best = None
                for a, b in pairs:
                    d = haversine_m(a[0], a[1], b[0], b[1])
                    if best is None or d < best[0]:
                        best = (d, a, b)
                if best is None:
                    continue
                d, a, b = best
                if d <= 0.01:
                    continue
                if d > GAP_THRESHOLD_M:
                    continue
                raw_gaps_for_street.append({
                    "lat": (a[0] + b[0]) / 2,
                    "lon": (a[1] + b[1]) / 2,
                    "street": street,
                    "type": "probable_disconnect",
                    "way1_id": wi["id"],
                    "way2_id": wj["id"],
                    "distance_m": round(d, 1),
                })

        raw_gaps_for_street.sort(key=lambda g: g["distance_m"])
        clustered_for_street: list[dict] = []
        for g in raw_gaps_for_street:
            collapsed = False
            for existing in clustered_for_street:
                if (
                    haversine_m(g["lat"], g["lon"], existing["lat"], existing["lon"])
                    <= GAP_CLUSTER_M
                ):
                    collapsed = True
                    break
            if not collapsed:
                clustered_for_street.append(g)
        gaps.extend(clustered_for_street)
    return gaps
