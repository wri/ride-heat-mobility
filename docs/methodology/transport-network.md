# Transport network

→ [Back to index](index.md)

## Walking network

The model uses the OpenStreetMap (OSM) pedestrian network for Nairobi, downloaded via osmnx with `network_type="walk"`. This includes footways, paths, and roads where pedestrian movement is permitted.

<!-- TODO: discuss completeness of OSM pedestrian data in Nairobi — informal footpaths through estates, missing links, known gaps -->

## Matatu network (GTFS)

<!-- TODO: describe DigitalMatatus data, how it was collected (crowd-sourced GPS traces), coverage, vintage, limitations -->

### What GTFS captures

<!-- TODO: stops, routes, approximate travel times -->

### What GTFS does not capture

<!-- TODO: no real-time headways, no fare-based access barriers, informal stops not in the feed, bodaboda not modelled -->

## Graph construction decisions

<!-- TODO: why we project to EPSG:4326 after adding speeds; why retain_all=False; how access links are weighted; why transit edges use departure_time as the primary scheduling attribute -->

## Known network gaps

<!-- TODO: list specific areas where the network is known to be incomplete and how this affects model outputs -->

See [References](references.md) for data sources and full citations.
