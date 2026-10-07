# Transport network

→ [Back to index](index.md)

## Walking network

The model uses the OpenStreetMap (OSM) pedestrian network for Nairobi, downloaded via osmnx with `network_type="walk"`. This includes footways, paths, and roads where pedestrian movement is permitted.

<!-- TODO: discuss completeness of OSM pedestrian data in Nairobi — informal footpaths through estates, missing links, known gaps -->

## Matatu network (GTFS)

The matatu (informal minibus) network comes from [DigitalMatatus](http://www.digitalmatatus.com) (University of Nairobi & MIT Civic Data Design Lab), a crowd-sourced GTFS feed built from rider GPS traces. The project ships two exports for the same underlying data: a GIS shapefile package (`GIS_DATA_2019.zip`, stops/route-shapes only, no schedule/frequency information) and a full GTFS feed (`GTFS_FEED_2019.zip`). Only the GTFS feed is used — the shapefile export is a strict subset of it (its own README documents every field as identical to, or a rollup of, the GTFS fields), so parsing both would be redundant.

The 2019 Nairobi feed covers 136 routes, 272 trips, and 4,285 stops. Its `feed_info.txt` labels it `"TRAINING"` data, and every stop has a uniform 20-second dwell time — both signs this is DigitalMatatus's demonstration-quality release rather than a fully validated field survey, though it's structurally sound to build on.

<!-- TODO: confirm vintage/coverage claims once a non-demo feed is available; note any known route gaps -->

### What GTFS captures

Stops, routes, and — critically — **service frequency, not a literal timetable**: every trip in `stop_times.txt` is a single reference run (all 272 trips in the 2019 feed start at the identical nominal clock time `6:00:20`), and how often that trip actually runs comes entirely from `frequencies.txt`, as headway bands (e.g. every 5 minutes 6:00–9:00, every 15 minutes 9:00–15:00). `data/graph.py::_integrate_gtfs()` uses `stop_times.txt` only for the *relative* ride time between consecutive stops, and stores each trip's frequency bands directly on its transit edges so `model/routing.py::route_transit()` can tell whether a route is in service at an agent's actual departure time, instead of trying to match a departure clock time that doesn't meaningfully exist in this data.

The headway values themselves are **not** used for the boarding wait. Every trip in the 2019 feed has identical headways (5 min 06–09 and 15–21, 15 min 09–15), which reads as a placeholder schedule. The wait is instead drawn from `Exponential(mean = transit_mean_wait_min)`, with the mean (5.65 min) fit to the WRI rider survey — see [Travel behaviour](travel-behaviour.md#transit-wait-time-and-wait-tolerance). The exponential (rather than a fixed wait) models matatus as an irregular, memoryless paratransit service with no real-time schedule adherence.

### What GTFS does not capture

No real-time headway adherence (the model uses the published bands only to decide whether a route is running; wait times come from the rider survey instead), no fare-based access barriers, no informal/unofficial stops outside the surveyed network, and bodaboda (motorcycle taxi) trips aren't modeled at all. Transfers between routes are only free where two routes happen to share a physical stop node in the feed — no fare/time penalty is charged for platform-to-platform transfer walking, and transfer wait time isn't charged at all (only the very first boarding's wait is).

## Graph construction decisions

<!-- TODO: why we project to EPSG:4326 after adding speeds; why retain_all=False -->

Transit stop nodes get synthetic IDs starting at `10**13`, chosen to sit well clear of any real OSM node ID for this bbox (observed max ~1.4×10¹⁰). Access-link edges (stop ↔ nearest walk-network node) are weighted the same way as a walk edge (`length` from Haversine distance, `travel_time = length / 1.2`), so a rider approaching or leaving a stop is genuinely just walking. A transit ride itself is *not* traversed at the agent's personal walk speed — `model/agent.py`'s `AgentPool.edge_speed_mps` holds the effective speed for whichever edge the agent is currently on, set to the transit edge's own `length / travel_time` while riding (see `model/routing.py::_activate_edge()`), so a matatu segment moves at the matatu's implied road speed regardless of the individual rider's walking pace.

## Known network gaps

<!-- TODO: list specific areas where the network is known to be incomplete and how this affects model outputs -->

See [References](references.md) for data sources and full citations.
