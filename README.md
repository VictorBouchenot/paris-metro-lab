# paris-metro-lab

Journey routing on the real Paris metro timetable in Python: parse the
official Ile-de-France Mobilities GTFS feed, group platforms into stations,
build time-dependent connections, and compute earliest-arrival routes and
isochrone maps with a Connection Scan Algorithm (CSA) — validated both
against the feed itself and against independently published journey-time
estimates.

Motivation: the metro is how Paris actually moves. I wanted a router whose
answers come from the real timetable — not straight-line distances or average
speeds — and whose numbers I can check, line by line, against an outside
source.

## What it does

```bash
python -m metro_lab.cli download                     # fetch + extract the GTFS feed
python -m metro_lab.cli route "Châtelet" "La Défense" --date 2026-11-24 --time 08:30
python -m metro_lab.cli isochrone "Châtelet" --gif examples/isochrone.gif
python -m metro_lab.cli validate
python -m unittest discover -s tests
```

Example output for `route "Porte de Clignancourt" "Olympiades"` (Tue
2026-11-24, 08:30):

```
line   4  08:30 Porte de Clignancourt -> 08:45 Châtelet
line  14  08:48 Châtelet -> 08:56 Olympiades
Total: 27 min (in-vehicle + modeled transfers, theoretical timetable)
```

`isochrone` draws every station colored by travel-time band from the origin
(and optionally an animated GIF of the reachable area growing minute by
minute). From Châtelet at 08:30 on a weekday, all 321 metro stations are
reachable within 45 minutes on the theoretical timetable.

## Method

- **Stations, not platforms.** The feed models every platform and entrance
  separately (35,508 stops). We follow `parent_station` links up to the
  top-level station, leaving 321 metro stations.
- **Connections.** Each pair of consecutive stops of a trip becomes one
  connection `(from_station, to_station, dep, arr)`, with GTFS times past
  24:00 handled as seconds since midnight. For Tuesday 2026-11-24 this gives
  284,988 metro connections.
- **Routing.** A Connection Scan Algorithm: one pass over connections sorted
  by departure time. Boarding a *new* trip at a station requires being ready
  there: arrival time plus the station's change time (minimum transfer time
  from `transfers.txt`, default 3 min where the feed does not say). Staying
  on the same trip costs nothing. Walking transfers between distinct
  stations (e.g. Saint-Lazare ↔ Europe) use the feed's `min_transfer_time`.
  A full earliest-arrival scan from one station takes ~0.2 s.
- **Service calendar.** `calendar.txt` weekday flags plus
  `calendar_dates.txt` exceptions (added/removed services) decide which
  trips run on the requested date.

## Validation

Two layers, kept separate on purpose.

**1. Internal consistency (must hold by construction).** We sample 50
connections from a weekday, start a scan at the connection's origin one
minute before its departure, and check that the router reaches the
connection's destination no later than its scheduled arrival: 50/50 pass.
Ten unit tests cover the algorithm itself (transfer penalties, staying on
the same trip, walking links, post-midnight times, calendar exceptions,
itinerary reconstruction).

**2. External comparison.** Computed times vs. the fastest-route estimates
published by itineraire-metro.paris (consulted 2026-11-19), which — like our
model — exclude walking to/from the stations and the initial wait:

| Route | Ours | Published | Diff |
|---|---|---|---|
| Châtelet → La Défense | 21 min | 27 min | −6 min |
| Porte de Clignancourt → Olympiades | 27 min | 32 min | −5 min |
| Nation → Porte de Champerret | 27 min | 40 min | −13 min |

Our times are systematically lower, and we can say why rather than hide it:
we board at the requested departure time exactly (zero initial wait), while
the reference pads each segment (its own per-stop times work out to about
2.7 min/stop, against ~1.4 min in the official timetable). On the third
route the two also disagree on the path: we go line 1 → 14 → walk
Saint-Lazare–Europe → line 3, matching the real network's fastest pattern,
while the reference routes through Châtelet. The comparison therefore
validates order of magnitude and routing plausibility, not exact equality —
these are third-party estimates, not official IDFM figures.

## Limits (read before trusting a number)

- **Metro only**: lines 1–14 including 3bis and 7bis. No RER, Transilien,
  bus, tram or funicular, so some real-world fastest routes are invisible to
  this router.
- **Theoretical timetable.** No real-time traffic, works or disruptions.
  Feed validity window: mid-November to mid-December 2026 depending on the
  service (most services run 2026-11-18 → 2026-12-17).
- **Station-to-station.** No walking from your door to the first station or
  from the last station to your destination, and no initial waiting time if
  you ask for a departure exactly when a train leaves.
- Transfer times come from the feed's `min_transfer_time`; where it is
  silent, a flat 3-minute change penalty is assumed.

## Data

Ile-de-France Mobilities GTFS feed (all networks), mirrored by OpenDataSoft:
<https://eu.ftp.opendatasoft.com/stif/GTFS/IDFM-gtfs.zip> (~114 MB zip,
fetched 2026-11-18). The metro subset used here: 16 routes, 33,704 trips,
832,586 stop_times, 321 stations. Raw data is not committed (`data/` is
gitignored); `download` re-fetches it.

## Layout

```
src/metro_lab/
  download.py    fetch + extract the feed
  gtfs.py        parsing, station grouping, calendars, connections, footpaths
  csa.py         connection scan, itinerary reconstruction
  isochrone.py   travel-time maps (static PNG, animated GIF)
  validate.py    internal consistency + external comparison
  cli.py         download / route / isochrone / validate
tests/           unit tests on a synthetic two-line network
examples/        generated maps (gitignored)
```

Pure Python + pandas/numpy/matplotlib; tests use the standard-library
unittest runner.
