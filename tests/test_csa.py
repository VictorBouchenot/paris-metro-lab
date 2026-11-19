import unittest

import pandas as pd

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from metro_lab import csa, gtfs  # noqa: E402


def make_network():
    """Two lines crossing at station X, plus a walking-only link C-D."""
    stops = pd.DataFrame(
        {
            "stop_id": ["A", "X", "B", "C", "D"],
            "stop_name": ["A", "X", "B", "C", "D"],
            "parent_station": ["", "", "", "", ""],
            "stop_lat": ["48.85"] * 5,
            "stop_lon": ["2.33", "2.34", "2.35", "2.36", "2.37"],
            "location_type": ["1"] * 5,
        }
    )
    s2s = gtfs.build_stop_to_station(stops)
    # Trip 1: A -> X -> B ; trip 2: X -> C
    stop_times = pd.DataFrame(
        {
            "trip_id": ["t1"] * 3 + ["t2"] * 2,
            "arrival_time": ["08:00:00", "08:10:00", "08:20:00", "08:12:00", "08:22:00"],
            "departure_time": ["08:00:00", "08:10:00", "08:20:00", "08:12:00", "08:22:00"],
            "stop_id": ["A", "X", "B", "X", "C"],
            "stop_sequence": ["1", "2", "3", "1", "2"],
        }
    )
    trips = pd.DataFrame(
        {"trip_id": ["t1", "t2"], "route_id": ["r1", "r2"], "service_id": ["wk", "wk"]}
    )
    conns = gtfs.build_connections(stop_times, trips, s2s)
    footpaths = {"B": [("D", 600)], "D": [("B", 600)]}
    change = {s: 180 for s in "AXBCD"}
    return conns, ["A", "X", "B", "C", "D"], footpaths, change


class TestCSA(unittest.TestCase):
    def setUp(self):
        self.conns, self.stations, self.fp, self.change = make_network()

    def scan(self, origin, t0):
        return csa.scan(self.conns, self.stations, self.fp, self.change, origin, t0)

    def test_direct_ride(self):
        res = self.scan("A", 8 * 3600)
        i = self.stations.index("B")
        self.assertEqual(res.earliest[i], 8 * 3600 + 20 * 60)

    def test_transfer_respects_change_time(self):
        # Arrive X at 08:10; line 2 leaves 08:15 -> missed (180s change); no later
        # trip -> C unreachable.
        res = self.scan("A", 8 * 3600)
        self.assertEqual(res.earliest[self.stations.index("C")], csa.INF)

    def test_transfer_possible_with_shorter_change(self):
        self.change["X"] = 60  # arrive 08:10, ready 08:11, board 08:12
        res = self.scan("A", 8 * 3600)
        self.assertEqual(res.earliest[self.stations.index("C")], 8 * 3600 + 22 * 60)

    def test_walking_transfer(self):
        res = self.scan("B", 9 * 3600)
        # B -(600s walk)-> D
        self.assertEqual(res.earliest[self.stations.index("D")], 9 * 3600 + 600)

    def test_origin_ready_without_change_penalty(self):
        res = self.scan("X", 8 * 3600 + 12 * 60)  # board exactly at departure
        self.assertEqual(res.earliest[self.stations.index("C")], 8 * 3600 + 22 * 60)

    def test_reconstruct_merges_same_trip(self):
        res = self.scan("A", 8 * 3600)
        legs = csa.reconstruct_path(res, self.conns, "A", "B")
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["trip_id"], "t1")
        self.assertEqual(legs[0]["to"], "B")


class TestGtfsHelpers(unittest.TestCase):
    def test_parse_gtfs_time_past_midnight(self):
        self.assertEqual(gtfs.parse_gtfs_time("25:05:00"), 25 * 3600 + 300)

    def test_stop_to_station_follows_chain(self):
        stops = pd.DataFrame(
            {
                "stop_id": ["p1", "s1"],
                "parent_station": ["s1", ""],
            }
        )
        self.assertEqual(gtfs.build_stop_to_station(stops), {"p1": "s1", "s1": "s1"})

    def test_active_services_with_exception(self):
        calendar = pd.DataFrame(
            {
                "service_id": ["wk"],
                "monday": ["1"], "tuesday": ["1"], "wednesday": ["1"],
                "thursday": ["1"], "friday": ["1"], "saturday": ["0"], "sunday": ["0"],
                "start_date": ["20260101"], "end_date": ["20261231"],
            }
        )
        cal_dates = pd.DataFrame(
            {"service_id": ["wk", "sp"], "date": ["20261121", "20261121"], "exception_type": ["2", "1"]}
        )
        # Saturday 2026-11-21: wk removed by exception, sp added.
        active = gtfs.active_services(calendar, cal_dates, pd.Timestamp("2026-11-21"))
        self.assertEqual(active, {"sp"})
        # Tuesday 2026-11-24: plain weekday service.
        self.assertEqual(
            gtfs.active_services(calendar, cal_dates, pd.Timestamp("2026-11-24")), {"wk"}
        )

    def test_connections_sorted_and_self_loops_dropped(self):
        conns, *_ = make_network()
        self.assertTrue(conns.dep.is_monotonic_increasing)
        self.assertFalse((conns.from_station == conns.to_station).any())


if __name__ == "__main__":
    unittest.main()
