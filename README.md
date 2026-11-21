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
2026-11-24, requested departure 08:30):

```
line   4  08:30 Porte de Clignancourt -> 08:45 Châtelet
line  14  08:48 Châtelet -> 08:56 Olympiades
Total: 27 min (in-vehicle + modeled transfers, theoretical timetable)
```

Duration convention: a reported duration is computed in seconds from the
*requested* departure time to the scheduled arrival, so it includes waiting
for the first train (here the first métro leaves 30 s after 08:30). Displayed
clock times are truncated to the minute (08:30:30 shows as 08:30); the total
is rounded to the nearest minute from the exact seconds (here 1608 s = 26.8
min, shown as 27).

`isochrone` draws every station colored by travel-time band from the origin
(and optionally an animated GIF of the reachable area growing minute by
minute). From Châtelet at 08:30 on a weekday, all 321 metro stations are
reachable within 45 minutes on the theoretical timetable.

## Interactive map

`python -m metro_lab.cli web` builds a static page in `docs/` (no backend,
no JavaScript dependencies): pick the origin station and the departure time,
drag the time-budget slider or press play to watch the reachable area grow.
It runs anywhere static files are served; on GitHub the repo enables Pages from the `docs/` folder of `main`.

How it works: the router precomputes earliest-arrival scans from every one
of the 321 stations at three preset departures (08:30, 12:30, 18:30 on the
chosen weekday) and stores the minutes, quantized to 30 s, in a 1.5 MB
`data.json`. The page only reads that file; it never recomputes routes.
Consequences, stated honestly: interactivity is limited to those preset
departure times, and everything shown comes from the same theoretical
timetable as the rest of the project. Regenerating the data takes a few
minutes (321 scans per departure time). Deep links are supported:
`docs/index.html?origin=Nation&time=2&min=45`.

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
This shows the router can ride sampled scheduled connections; it does **not**
by itself prove that returned routes are optimal or that every transfer is
modeled correctly. Ten unit tests cover the algorithm itself (transfer
penalties, staying on the same trip, walking links, post-midnight times,
calendar exceptions, itinerary reconstruction).

**2. External comparison.** Computed times vs. the fastest-route estimates
published by itineraire-metro.paris (consulted 2026-11-19), whose pages
state they exclude walking to/from the stations and the wait to reach them.
Same requested departure for all three: Tue 2026-11-24, 08:30.

| Route | Ours | Published | Diff (ours − published) |
|---|---|---|---|
| Châtelet → La Défense | 21.0 min | 27 min | −6.0 min |
| Porte de Clignancourt → Olympiades | 26.8 min | 32 min | −5.2 min |
| Nation → Porte de Champerret | 26.5 min | 40 min | −13.5 min |

What we know about these gaps, and what we do not:

- Our durations are exact to the second from the requested time and already
  include the wait for the first train (e.g. 87 s at Châtelet: first
  departure 08:31:27 for a 08:30:00 request).
- The reference site does not document its model, so we cannot explain the
  residual differences from the inside. They are third-party estimates, not
  official IDFM figures, and neither side is measured against real-world
  travel times here: our numbers come from the theoretical timetable, which
  is not the same as what happens on the tracks.
- On the third pair the two routers also choose different paths (ours:
  line 1 → 14 → walk Saint-Lazare–Europe → line 3; theirs goes through
  Châtelet), which alone accounts for part of the larger gap.

The comparison therefore supports order of magnitude and routing
plausibility only. It does not show our model is more accurate than the
reference.

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
  webexport.py   precomputed scans + static interactive page
  cli.py         download / route / isochrone / validate / web
tests/           unit tests on a synthetic two-line network
examples/        generated maps (gitignored)
docs/            interactive page: index.html + precomputed data.json
```

Pure Python + pandas/numpy/matplotlib; tests use the standard-library
unittest runner.
