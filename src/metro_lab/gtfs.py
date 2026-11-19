"""GTFS loading: station grouping, service calendars, connections, footpaths.

Conventions
-----------
- A "station" is the top-level parent stop (location_type 1). Platforms and
  entrances point to it through parent_station (depth 1 in the IDFM feed,
  but we follow the chain defensively).
- Times are seconds since midnight and may exceed 24h (GTFS convention).
- A "connection" is one ride between two consecutive stops of one trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

METRO_ROUTE_TYPE = "1"
DEFAULT_CHANGE_SECONDS = 180  # fallback same-station line-change penalty


def _read(gtfs_dir: Path, name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(Path(gtfs_dir) / name, dtype=str, keep_default_na=False, **kw)


def build_stop_to_station(stops: pd.DataFrame) -> dict[str, str]:
    """Map every stop_id to its top-level parent station id."""
    parent = dict(zip(stops.stop_id, stops.parent_station))

    def root(sid: str) -> str:
        seen = set()
        while parent.get(sid, "") and sid not in seen:
            seen.add(sid)
            sid = parent[sid]
        return sid

    return {sid: root(sid) for sid in stops.stop_id}


def parse_gtfs_time(t: str) -> int:
    """'HH:MM:SS' -> seconds since midnight; HH may exceed 23."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def active_services(calendar: pd.DataFrame, calendar_dates: pd.DataFrame, date: pd.Timestamp) -> set[str]:
    """Service ids running on `date`, from calendar.txt plus calendar_dates.txt exceptions."""
    d = date.strftime("%Y%m%d")
    weekday = date.day_name().lower()
    cal = calendar[(calendar.start_date <= d) & (calendar.end_date >= d)]
    active = set(cal.loc[cal[weekday] == "1", "service_id"])
    exc = calendar_dates[calendar_dates.date == d]
    active |= set(exc.loc[exc.exception_type == "1", "service_id"])
    active -= set(exc.loc[exc.exception_type == "2", "service_id"])
    return active


def build_connections(
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    stop_to_station: dict[str, str],
    services: set[str] | None = None,
) -> pd.DataFrame:
    """Consecutive-stop ride pairs for the given trips.

    Returns a DataFrame with from_station, to_station, dep (s), arr (s), trip_id,
    sorted by departure time. If `services` is given, only trips whose service_id
    is in the set are kept.
    """
    if services is not None:
        trips = trips[trips.service_id.isin(services)]
    st = stop_times[stop_times.trip_id.isin(set(trips.trip_id))].copy()
    st = st.sort_values(["trip_id", "stop_sequence"], key=lambda c: c.astype(int) if c.name == "stop_sequence" else c)
    st["next_stop"] = st.groupby("trip_id").stop_id.shift(-1)
    st["next_arr"] = st.groupby("trip_id").arrival_time.shift(-1)
    st = st.dropna(subset=["next_stop"])
    conns = pd.DataFrame(
        {
            "from_station": st.stop_id.map(stop_to_station),
            "to_station": st.next_stop.map(stop_to_station),
            "dep": st.departure_time.map(parse_gtfs_time).astype(np.int64),
            "arr": st.next_arr.map(parse_gtfs_time).astype(np.int64),
            "trip_id": st.trip_id,
        }
    )
    # Loops back to the same station carry no travel information.
    conns = conns[conns.from_station != conns.to_station]
    return conns.sort_values("dep", kind="mergesort").reset_index(drop=True)


def build_footpaths(
    transfers: pd.DataFrame,
    stop_to_station: dict[str, str],
    station_ids: set[str],
) -> tuple[dict[str, list[tuple[str, int]]], dict[str, int]]:
    """Walking edges between distinct stations, and per-station change times.

    Returns (footpaths, change_seconds): footpaths maps a station to
    [(other_station, seconds)], change_seconds is the minimum time to switch
    lines inside one station (from same-station transfers, else default).
    """
    t = transfers.copy()
    t["fs"] = t.from_stop_id.map(stop_to_station)
    t["ts"] = t.to_stop_id.map(stop_to_station)
    t["secs"] = pd.to_numeric(t.min_transfer_time, errors="coerce")
    t = t.dropna(subset=["secs"])
    t["secs"] = t.secs.astype(int)
    t = t[t.fs.isin(station_ids) & t.ts.isin(station_ids)]

    cross = t[t.fs != t.ts].groupby(["fs", "ts"]).secs.min()
    footpaths: dict[str, list[tuple[str, int]]] = {}
    for (fs, ts), secs in cross.items():
        footpaths.setdefault(fs, []).append((ts, int(secs)))

    same = t[t.fs == t.ts].groupby("fs").secs.min()
    change = {s: DEFAULT_CHANGE_SECONDS for s in station_ids}
    for s, secs in same.items():
        change[s] = max(0, int(secs))
    return footpaths, change


@dataclass
class MetroNetwork:
    """Everything the router needs for one feed."""

    stations: pd.DataFrame  # index station_id, columns stop_name, lat, lon
    routes: pd.DataFrame  # metro routes only (route_id, route_short_name, ...)
    trips: pd.DataFrame  # metro trips only
    stop_times: pd.DataFrame  # stop_times of metro trips only
    transfers: pd.DataFrame
    calendar: pd.DataFrame
    calendar_dates: pd.DataFrame
    stop_to_station: dict[str, str]
    footpaths: dict[str, list[tuple[str, int]]]
    change_seconds: dict[str, int]

    def connections_for_date(self, date: pd.Timestamp) -> pd.DataFrame:
        services = active_services(self.calendar, self.calendar_dates, date)
        return build_connections(self.stop_times, self.trips, self.stop_to_station, services)


def load_metro_network(gtfs_dir: Path) -> MetroNetwork:
    """Load the feed and keep only the metro (route_type 1) subnetwork."""
    gtfs_dir = Path(gtfs_dir)
    stops = _read(gtfs_dir, "stops.txt")
    routes = _read(gtfs_dir, "routes.txt")
    trips_all = _read(gtfs_dir, "trips.txt")
    calendar = _read(gtfs_dir, "calendar.txt")
    calendar_dates = _read(gtfs_dir, "calendar_dates.txt")
    transfers = _read(gtfs_dir, "transfers.txt")

    stop_to_station = build_stop_to_station(stops)

    metro_routes = set(routes.loc[routes.route_type == METRO_ROUTE_TYPE, "route_id"])
    trips = trips_all[trips_all.route_id.isin(metro_routes)].copy()

    st = _read(
        gtfs_dir,
        "stop_times.txt",
        usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
    )
    trip_ids = set(trips.trip_id)
    stop_times = st[st.trip_id.isin(trip_ids)].copy()

    station_ids = {stop_to_station[s] for s in set(stop_times.stop_id)}
    station_rows = stops.set_index("stop_id").loc[sorted(station_ids)]
    stations = station_rows[["stop_name", "stop_lat", "stop_lon"]].copy()
    stations["stop_lat"] = stations.stop_lat.astype(float)
    stations["stop_lon"] = stations.stop_lon.astype(float)

    footpaths, change_seconds = build_footpaths(transfers, stop_to_station, station_ids)

    return MetroNetwork(
        stations=stations,
        routes=routes[routes.route_type == METRO_ROUTE_TYPE].copy(),
        trips=trips,
        stop_times=stop_times,
        transfers=transfers,
        calendar=calendar,
        calendar_dates=calendar_dates,
        stop_to_station=stop_to_station,
        footpaths=footpaths,
        change_seconds=change_seconds,
    )


def find_station(stations: pd.DataFrame, name: str) -> str:
    """Case-insensitive exact-then-substring match on station names."""
    exact = stations[stations.stop_name.str.casefold() == name.casefold()]
    if len(exact) == 1:
        return exact.index[0]
    sub = stations[stations.stop_name.str.casefold().str.contains(name.casefold(), regex=False)]
    if len(sub) == 1:
        return sub.index[0]
    if len(sub) == 0:
        raise KeyError(f"No station matches {name!r}")
    raise KeyError(f"Ambiguous station {name!r}: {sorted(sub.stop_name.unique())[:10]}")
