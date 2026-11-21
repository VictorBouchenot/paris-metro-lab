"""Command-line interface: download, route, isochrone, validate."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import csa, gtfs, isochrone

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
GTFS_DIR = DATA_DIR / "gtfs"


def _load() -> gtfs.MetroNetwork:
    if not GTFS_DIR.exists():
        raise SystemExit(f"No GTFS data at {GTFS_DIR}. Run: python -m metro_lab.cli download")
    return gtfs.load_metro_network(GTFS_DIR)


def _parse_when(args) -> tuple[pd.Timestamp, int]:
    date = pd.Timestamp(args.date)
    h, m = args.time.split(":")
    return date, int(h) * 3600 + int(m) * 60


def cmd_download(args) -> None:
    from .download import download_gtfs

    download_gtfs(DATA_DIR)


def cmd_route(args) -> None:
    net = _load()
    date, t0 = _parse_when(args)
    origin = gtfs.find_station(net.stations, args.origin)
    dest = gtfs.find_station(net.stations, args.dest)
    conns = net.connections_for_date(date)
    res = csa.scan(conns, list(net.stations.index), net.footpaths, net.change_seconds, origin, t0)
    legs = csa.reconstruct_path(res, conns, origin, dest)
    if not legs:
        print(f"No route from {args.origin} to {args.dest} on {date.date()} after {args.time}.")
        return
    trip_meta = net.trips.set_index("trip_id")
    route_names = dict(zip(net.routes.route_id, net.routes.route_short_name))
    names = net.stations.stop_name
    print(f"{names[origin]} -> {names[dest]}, {date.date()} depart {args.time}")
    for leg in legs:
        if leg["kind"] == "walk":
            print(f"  walk  {names[leg['from']]} -> {names[leg['to']]}")
        else:
            route_id = trip_meta.loc[leg["trip_id"], "route_id"]
            line = route_names.get(route_id, "?")
            print(f"  line {line:>3}  {csa.format_hhmm(leg['dep'])} {names[leg['from']]} -> "
                  f"{csa.format_hhmm(leg['arr'])} {names[leg['to']]}")
    total = (res.earliest[list(res.station_ids).index(dest)] - t0) / 60.0
    print(f"Total: {total:.0f} min (in-vehicle + modeled transfers, theoretical timetable)")


def cmd_isochrone(args) -> None:
    net = _load()
    date, t0 = _parse_when(args)
    origin = gtfs.find_station(net.stations, args.station)
    conns = net.connections_for_date(date)
    res = csa.scan(conns, list(net.stations.index), net.footpaths, net.change_seconds, origin, t0)
    name = net.stations.stop_name[origin]
    df = isochrone.plot_isochrone(res, net.stations, name, args.out, max_minutes=args.max_minutes)
    print(f"Wrote {args.out} ({len(df)} stations within {args.max_minutes} min)")
    if args.gif:
        isochrone.animate_isochrone(res, net.stations, name, args.gif, max_minutes=args.max_minutes)
        print(f"Wrote {args.gif}")


def cmd_web(args) -> None:
    from .webexport import write_web

    net = _load()
    date = pd.Timestamp(args.date)
    labels = args.times.split(",")
    times = [int(t.split(":")[0]) * 3600 + int(t.split(":")[1]) * 60 for t in labels]
    path = write_web(net, date, labels, times, Path(args.out))
    print(f"Wrote {path} (+ index.html). Serve the folder statically, e.g. GitHub Pages.")


def cmd_validate(args) -> None:
    from .validate import run_validation

    net = _load()
    run_validation(net, pd.Timestamp(args.date), args.time)


def main() -> None:
    p = argparse.ArgumentParser(prog="metro-lab", description=__doc__)
    sub = p.add_subparsers(required=True)
    sub.add_parser("download").set_defaults(func=cmd_download)
    for name, func, extra in (
        ("route", cmd_route, [("origin", {}), ("dest", {})]),
        ("isochrone", cmd_isochrone, [("station", {}), ("--out", {"default": "examples/isochrone.png"}),
                                      ("--gif", {"default": None}),
                                      ("--max-minutes", {"type": int, "default": 60})]),
        ("validate", cmd_validate, []),
        ("web", cmd_web, [("--out", {"default": "web"}),
                          ("--times", {"default": "08:30,12:30,18:30"})]),
    ):
        sp = sub.add_parser(name)
        for arg, kw in extra:
            sp.add_argument(arg, **kw)
        sp.add_argument("--date", default="2026-11-24", help="YYYY-MM-DD (a Tuesday in the feed validity)")
        sp.add_argument("--time", default="08:30", help="HH:MM local departure time")
        sp.set_defaults(func=func)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
