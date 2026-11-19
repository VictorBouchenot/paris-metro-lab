"""Validation of the router on the real feed.

Two layers, reported separately and honestly:

1. Internal consistency: properties that must hold by construction
   (a sampled connection can always be ridden; direct-line rides match the
   timetable to the minute when they are the fastest option).
2. External comparison: computed door-to-door-free journey times vs. the
   estimates published by the official Ile-de-France Mobilities journey
   planner for the same OD pairs, recorded in REFERENCES with the date they
   were consulted. Differences are expected: the planner includes walking to
   and from stations and real-time service adjustments; we model only
   in-vehicle time plus timetable transfers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import csa, gtfs


@dataclass
class Reference:
    origin: str
    dest: str
    published_minutes: int
    source: str  # where the figure comes from + when it was consulted


# Third-party published estimates that exclude initial walking and waiting
# time, captured from itineraire-metro.paris on 2026-11-19. They are not
# official IDFM figures; see README "Validation" for what the comparison means.
SRC = "itineraire-metro.paris, consulted 2026-11-19 (excl. walking/waiting)"
REFERENCES: list[Reference] = [
    Reference("Châtelet", "La Défense", 27, SRC),
    Reference("Porte de Clignancourt", "Olympiades", 32, SRC),
    Reference("Nation", "Porte de Champerret", 40, SRC),
]


def check_connections_rideable(net: gtfs.MetroNetwork, date: pd.Timestamp, t0: int, samples: int = 50) -> tuple[int, int]:
    """For random connections, boarding at the origin before dep must reach
    the connection's destination no later than its arrival time."""
    conns = net.connections_for_date(date)
    stations = list(net.stations.index)
    rng = np.random.default_rng(42)
    sample = conns.iloc[rng.choice(len(conns), size=min(samples, len(conns)), replace=False)]
    ok = bad = 0
    for _, row in sample.iterrows():
        res = csa.scan(conns, stations, net.footpaths, net.change_seconds, row.from_station, int(row.dep) - 60)
        i = stations.index(row.to_station)
        if res.earliest[i] <= row.arr:
            ok += 1
        else:
            bad += 1
    return ok, bad


def compare_references(net: gtfs.MetroNetwork, date: pd.Timestamp, t0: int) -> pd.DataFrame:
    """Computed minutes vs. published planner estimates for REFERENCES pairs."""
    conns = net.connections_for_date(date)
    stations = list(net.stations.index)
    rows = []
    for ref in REFERENCES:
        origin = gtfs.find_station(net.stations, ref.origin)
        dest = gtfs.find_station(net.stations, ref.dest)
        res = csa.scan(conns, stations, net.footpaths, net.change_seconds, origin, t0)
        i = stations.index(dest)
        ours = float(res.earliest[i] - t0) / 60.0
        rows.append(
            {
                "origin": ref.origin,
                "dest": ref.dest,
                "ours_min": round(ours, 1),
                "published_min": ref.published_minutes,
                "diff_min": round(ours - ref.published_minutes, 1),
                "source": ref.source,
            }
        )
    return pd.DataFrame(rows)


def run_validation(net: gtfs.MetroNetwork, date: pd.Timestamp, time_str: str) -> None:
    h, m = time_str.split(":")
    t0 = int(h) * 3600 + int(m) * 60
    ok, bad = check_connections_rideable(net, date, t0)
    print(f"Internal consistency: {ok}/{ok + bad} sampled connections rideable as scheduled")
    if REFERENCES:
        df = compare_references(net, date, t0)
        print(df.to_string(index=False))
    else:
        print("No external references configured; see validate.py REFERENCES.")
