# Attribution and data licenses

- MapLibre GL JS: BSD-3-Clause, https://github.com/maplibre/maplibre-gl-js
- shadcn/ui and Radix primitives: MIT, https://github.com/shadcn-ui/ui and https://github.com/radix-ui/primitives
- Turf: MIT, https://github.com/Turfjs/turf
- Fuse.js: Apache-2.0, https://github.com/krisk/Fuse
- Lucide: ISC, https://github.com/lucide-icons/lucide
- Other packages retain the notices included in their distributions and lockfile dependencies.

## Natural Earth

`public/world.geojson` is Natural Earth 1:110m Admin 0 Countries, public domain:
https://www.naturalearthdata.com/about/terms-of-use/

Source file: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson

## Etymology dataset

Etymology statements and translations in `data/seed.json` and translation drafts are adaptations of Wiktionary contributions. Individual articles and attribution links are recorded in `sources` and each analysis's `source_ids`.

Wiktionary contributors, CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/

Changes: extracted/condensed etymological accounts, Chinese/English glosses, normalized meanings, segmentation and editorial grouping. These are provisional adaptations awaiting review. Derivative etymology data must retain attribution and share-alike terms; the application MIT license does not override these terms.

Coordinates are approximate manually entered demonstration points. No proprietary map tiles are bundled.

## Online street basemap

OpenFreeMap public tiles: https://openfreemap.org/quick_start/
OpenMapTiles schema/style attribution: https://openmaptiles.org/
Map data © OpenStreetMap contributors, ODbL: https://www.openstreetmap.org/copyright

MapLibre's attribution control displays the online sources' attribution. Tiles, fonts and sprites load from OpenFreeMap on demand and are not redistributed in this repository. Street-level detail depends on OpenStreetMap coverage; the etymology dataset remains a separate curated layer.
