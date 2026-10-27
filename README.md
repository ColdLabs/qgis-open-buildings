# Open Buildings Downloader (QGIS plugin)

Downloads Google Open Buildings v3 footprints for the map view or the polygons of a layer, as polygons, centroid points or both. Attributes: `confidence`, `area_in_meters`, `full_plus_code`. Output CRS is EPSG:4326.

Coverage is Africa, South and Southeast Asia, Latin America and the Caribbean. Europe and North America have no data.

## Install

In QGIS: **Plugins → Manage and Install Plugins → All**, search for "Open Buildings Downloader", then **Install**. Requires QGIS 3.38 or later (Qt5 or Qt6). No extra Python packages are needed.

To install without the plugin repository, download the zip from the [latest release](https://github.com/ColdLabs/qgis-open-buildings/releases/latest) and use **Plugins → Manage and Install Plugins → Install from ZIP**.

## Use

- Toolbar button (Web toolbar) or **Web → Open Buildings**: opens the dialog with the current map extent filled in. If the active layer is a polygon layer with selected features, those become the area.
- **Processing Toolbox → Google Open Buildings → Download buildings**: same algorithm; works in models and batch mode.
- Command line:

```
qgis_process run openbuildings:download -- EXTENT="-23.53,-23.49,14.90,14.94 [EPSG:4326]" GEOMETRY=2 OUTPUT_POLYGONS=poly.gpkg OUTPUT_POINTS=pts.gpkg
```

`GEOMETRY`: 0 polygons, 1 points, 2 both. A building is kept when its centroid falls inside the area.

Layers loaded into QGIS are coloured by confidence, using the bands Google uses in its Earth Engine example (lower bound inclusive): green from 0.75, orange from 0.70 (Google uses yellow), red from 0.65, grey below 0.65. Google publishes nothing below 0.65, so grey only appears if the data changes. Files written by `qgis_process` carry no style.

## How it fetches data

Google publishes one gzipped CSV per S2 level-6 cell (about 100 km across) at `storage.googleapis.com/open-buildings-data/v3/`. The plugin works out which cells touch the area (`s2.py`), downloads those whole files and filters them locally. Polygon files have a median size of 9 MB and a maximum of 616 MB. Point files are about 4 times smaller, so "Points" downloads the point files.

Files are cached in `<QGIS profile>/cache/open_buildings/` and reused. Delete that folder to free space. The run stops before downloading if new downloads exceed the "Stop if new downloads exceed (MB)" value (2000 MB by default).

The plugin downloads through the QGIS network manager, so the proxy and SSL settings in QGIS apply.

## Data licence

Google Open Buildings is published by Google under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and [ODbL v1.0](https://opendatacommons.org/licenses/odbl/1-0/); you may use it under either. Credit Google Open Buildings when you publish maps or data made with it. See the [dataset page](https://sites.research.google/gr/open-buildings/). This plugin is not affiliated with Google.

## Development

Link the plugin folder into your QGIS profile instead of installing the zip (macOS, QGIS 4):

```
ln -s "$PWD/open_buildings_downloader" ~/Library/Application\ Support/QGIS/QGIS4/profiles/default/python/plugins/
```

`./build_zip.sh` writes `dist/open_buildings_downloader-<version>.zip` for upload to plugins.qgis.org.
`./check.sh` runs the scanners the plugin site runs: Bandit and detect-secrets block an upload, flake8 is advisory.

## Licence

GPL-2.0-or-later. See [LICENSE](LICENSE).
