"""Earliest-arrival routing over timetable connections (Connection Scan Algorithm).

Model
-----
- Nodes are stations (platforms grouped). Boarding a connection at station s
  requires ready[s] <= dep, where ready[s] is arrival time at s plus the
  station's line-change time (from same-station transfers, else a default).
- Walking transfers between distinct stations come from transfers.txt
  (min_transfer_time); walking makes you ready at the target station without
  an extra change penalty.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

INF = np.iinfo(np.int64).max // 4


@dataclass
class ScanResult:
    station_ids: list[str]
    origin: str
    earliest: np.ndarray  # earliest arrival time (raw, seconds) per station
    parent_conn: np.ndarray  # index into connections that set earliest, -1 if none
    parent_station: np.ndarray  # station index we arrived from (-1 at origin)

    def travel_minutes(self) -> dict[str, float]:
        """Travel time in minutes from origin for every reached station."""
        t0 = self.earliest[self.station_ids.index(self.origin)]
        return {
            sid: float(self.earliest[i] - t0) / 60.0
            for i, sid in enumerate(self.station_ids)
            if self.earliest[i] < INF
        }


def scan(
    conns: pd.DataFrame,
    station_ids: list[str],
    footpaths: dict[str, list[tuple[str, int]]],
    change_seconds: dict[str, int],
    origin: str,
    departure: int,
    default_change: int = 180,
) -> ScanResult:
    """Run CSA from `origin` at `departure` (seconds since midnight).

    `conns` must be sorted by dep. Returns earliest arrival per station with
    parent pointers for itinerary reconstruction.
    """
    idx = {s: i for i, s in enumerate(station_ids)}
    n = len(station_ids)
    o = idx[origin]

    fs = conns.from_station.map(idx).to_numpy(np.int64)
    ts = conns.to_station.map(idx).to_numpy(np.int64)
    dep = conns.dep.to_numpy(np.int64)
    arr = conns.arr.to_numpy(np.int64)
    trip_codes, trip_uniq = pd.factorize(conns.trip_id, sort=False)
    trip_boarded = np.full(len(trip_uniq), INF, dtype=np.int64)

    earliest = np.full(n, INF, dtype=np.int64)
    ready = np.full(n, INF, dtype=np.int64)
    parent_conn = np.full(n, -1, dtype=np.int64)
    parent_station = np.full(n, -1, dtype=np.int64)

    fp_idx = {idx[s]: [(idx[t], w) for t, w in lst if t in idx] for s, lst in footpaths.items() if s in idx}
    change = np.array([change_seconds.get(s, default_change) for s in station_ids], dtype=np.int64)

    def improve(station: int, t: int, via_conn: int, from_station: int) -> None:
        if t >= earliest[station]:
            return
        earliest[station] = t
        parent_conn[station] = via_conn
        parent_station[station] = from_station
        r = t + change[station]
        if r < ready[station]:
            ready[station] = r
        for other, w in fp_idx.get(station, ()):  # walking: ready immediately on arrival
            if t + w < earliest[other]:
                improve(other, t + w, -1, station)

    improve(o, departure, -1, -1)  # also relaxes footpaths from the origin
    ready[o] = departure  # at the origin we board at the departure time itself

    # Once a trip is boarded, its later connections need no change time: the
    # scan visits them in non-decreasing departure order within a trip.
    for c in range(len(conns)):
        d = dep[c]
        s_from = fs[c]
        aboard = trip_boarded[trip_codes[c]] <= d
        if not aboard:
            if ready[s_from] > d:
                continue
            trip_boarded[trip_codes[c]] = ready[s_from]
        a = arr[c]
        if a < earliest[ts[c]]:
            improve(int(ts[c]), int(a), c, int(s_from))

    return ScanResult(list(station_ids), origin, earliest, parent_conn, parent_station)


def reconstruct_path(res: ScanResult, conns: pd.DataFrame, origin: str, dest: str) -> list[dict]:
    """Backtrack the earliest-arrival itinerary to `dest` as ride/walk legs."""
    idx = {s: i for i, s in enumerate(res.station_ids)}
    if dest not in idx:
        raise KeyError(f"Unknown station {dest!r}")
    i = idx[dest]
    if res.earliest[i] >= INF:
        return []
    legs = []
    while i != idx[origin]:
        c = res.parent_conn[i]
        prev = res.parent_station[i]
        if c >= 0:
            row = conns.iloc[c]
            legs.append(
                {
                    "kind": "ride",
                    "from": res.station_ids[prev],
                    "to": res.station_ids[i],
                    "dep": int(row.dep),
                    "arr": int(row.arr),
                    "trip_id": row.trip_id,
                }
            )
        else:
            legs.append({"kind": "walk", "from": res.station_ids[prev], "to": res.station_ids[i]})
        i = prev
    legs.reverse()
    # Merge consecutive rides on the same trip into one leg.
    merged: list[dict] = []
    for leg in legs:
        if merged and leg["kind"] == "ride" and merged[-1].get("trip_id") == leg.get("trip_id"):
            merged[-1]["to"] = leg["to"]
            merged[-1]["arr"] = leg["arr"]
        else:
            merged.append(dict(leg))
    return merged


def format_hhmm(seconds: int) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"
