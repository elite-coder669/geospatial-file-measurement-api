# Geospatial File Measurement API

A small FastAPI service where you can upload a geospatial file, peek at what's inside it, and get basic measurements for every feature: polygon areas in m² and line lengths in m.

This is a learning project, so I kept the code deliberately simple: files are stored in memory, measurements run through the `pyproj.Geod` geodesic calculator, and there is no database or auth layer. The interesting stuff (file parsing, geometry handling, CRS edge cases) stays easy to follow.

---

## 1. Project Overview

The API accepts two file formats:

- **KML** (`.kml`): the Google-Earth-style XML format, read as a single file.
- **Zipped Shapefile** (`.zip`): an archive containing a Shapefile. The API extracts the archive, finds the first `.shp` file inside it, and reads that.

Once uploaded, each file gets an `id`. Then you can:

1. Fetch the file's metadata (filename, feature count, CRS, status).
2. Fetch per-feature measurements:
   - `Polygon` / `MultiPolygon` → area in square metres (m²)
   - `LineString` / `MultiLineString` → length in metres (m)
   - `Point` / `MultiPoint` → marked `NOT_REQUIRED` (points have no area or length)
   - anything else → marked `UNSUPPORTED`

Measurements use geodesic math directly on the WGS84 ellipsoid (via `pyproj.Geod`), so they never depend on a projected CRS. If a file's source CRS is not geographic, the geometry is converted to EPSG:4326 first.

## 2. Dataset Choice

For testing I picked the **Natural Earth Admin 0 – Countries** dataset (`ne_110m_admin_0_countries.*`), kept under `natural-earth-dataset/`. It turned out to be a solid stress test for three reasons:

- **Real boundaries.** These are real country outlines, not synthetic squares, so every measurement could be sanity-checked against known values (Australia ≈ 7.69M km², Brazil ≈ 8.51M km²).
- **Multiple geometry types.** The dataset mixes `Polygon` and `MultiPolygon` (island countries etc.), which made me exercise both geometry paths in the measurement code.
- **Awkward global shapes.** It has continent-wide features like Russia and Antarctica, plus tiny islands sitting right next to the ±180° longitude seam, like Fiji. Those are exactly the ones that break naive CRS handling (see §6).

The dataset is in EPSG:4326 (lon/lat), which is exactly what the geodesic calculator wants.

Note: this dataset is only for development and testing. The API reads whatever KML or zipped Shapefile you give it, so Natural Earth is not needed to run the thing.

## 3. Setup

Prerequisites:

- Python 3.12+ (the project was built against it)
- A virtual environment (the repo uses `.api/`)

Install dependencies:

```bash
python -m venv .api
.api/bin/pip install --upgrade pip
.api/bin/pip install -r requirements.txt
```

`requirements.txt` pins the web stack (FastAPI, uvicorn, python-multipart, pydantic, …). The geospatial packages the code actually uses (`geopandas`, `shapely`, `pyproj`, `numpy`, `pandas`) are in the environment but not listed in that file, so install them separately:

```bash
.api/bin/pip install geopandas shapely pyproj numpy pandas
```

(If you start fresh without the committed venv, you must do this step, since the app imports all of them.)

Run the server:

```bash
.api/bin/uvicorn main:app --reload
```

The API will be live at `http://127.0.0.1:8000`, with interactive docs at `http://127.0.0.1:8000/docs`.

Run the test suite:

```bash
.api/bin/python -m pytest test_api.py -q
```

Expected result: **13 passed**.

## 4. API Documentation

Every response is JSON. Files live in memory, so anything uploaded disappears once the server restarts.

### `GET /`: Health check

```bash
curl http://127.0.0.1:8000/
```

```json
{"status": "API is Active."}
```

### `POST /api/files/`: Upload a file

Send a KML file or a zipped Shapefile as multipart form data, using the field name `file`.

```bash
curl -F "file=@shapes.kml" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "47b71ebe-a902-4e51-b7a8-2834abcdf2a0",
  "filename": "shapes.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

Sending a `.zip` with a shapefile inside:

```bash
curl -F "file=@shapes.zip" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "5d90f7c1-...",
  "filename": "shapes.zip",
  "feature_count": 2,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

Errors: all return `400`:

| Case | Message |
|------|---------|
| File is not `.kml` or `.zip` | `Only KML and ZIP files are supported` |
| ZIP contains no `.shp` | `ZIP contains no Shapefile` |
| File cannot be parsed (bad KML, corrupt/garbage Shapefile, …) | `Unable to read geospatial file` |

Note: a broken Zip (like a `.zip` whose `.shp` is garbage) comes back as a clean `400` instead of crashing the server.

### `GET /api/files/{file_id}/`: File metadata

```bash
curl http://127.0.0.1:8000/api/files/47b71ebe-a902-4e51-b7a8-2834abcdf2a0/
```

```json
{
  "id": "47b71ebe-a902-4e51-b7a8-2834abcdf2a0",
  "filename": "shapes.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

Unknown id → `404` `{"detail": "File not found"}`.

### `GET /api/files/{file_id}/measurements/`: Per-feature measurements

```bash
curl http://127.0.0.1:8000/api/files/47b71ebe-a902-4e51-b7a8-2834abcdf2a0/measurements/
```

```json
{
  "file_id": "47b71ebe-a902-4e51-b7a8-2834abcdf2a0",
  "measurements": [
    {
      "id": "0",
      "geometry_type": "Polygon",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]]]
      },
      "crs": "EPSG:4326",
      "properties": {"Name": "poly", "tessellate": -1, "extrude": 0, "visibility": -1},
      "measurement": {
        "area": 12308778361.469452,
        "area_unit": "m²",
        "length": null,
        "length_unit": null,
        "status": "SUCCESS"
      }
    }
  ]
}
```

The `geometry` field is GeoJSON (from Shapely's `__geo_interface__`), `properties` holds the source file's attribute columns (missing values are skipped), and `measurement` works like this:

- `SUCCESS`: area (m²) for polygons, length (m) for lines
- `NOT_REQUIRED`: points, and empty or null geometries
- `UNSUPPORTED`: any geometry type that isn't polygon/line/point
- `FAILED`: the measurement raised an error (the API degrades per-feature; the rest of the file still returns)

Unknown id → `404` `{"detail": "File not found"}`.

## 5. Architecture and Workflow

```
geo-api/
├── main.py                 # FastAPI app; includes the router
├── app.py                  # All routes + parsing + measurement logic
├── models.py               # Pydantic response schemas
├── test_api.py             # FastAPI TestClient suite (13 tests)
├── requirements.txt        # Pinned pip dependencies
├── natural-earth-dataset/  # Test data (Admin 0 countries shapefile)
└── eda.ipynb               # Exploratory analysis notebook
```

- `main.py` sets up the `FastAPI` app and includes `app.router`. To run the API, just do `uvicorn main:app`.
- `app.py` owns the logic. Files live in the module-level `files_db` dict, keyed by a UUID.
- `models.py` defines the response schemas: `FileResponse`, `MeasurementsResponse`, `FeatureResponse`, `Measurement`.

**Upload flow** (`POST /api/files/`):

1. The extension is checked; anything that isn't `.kml`/`.zip` gets `400`.
2. For KML, the bytes are read directly with GeoPandas (`gpd.read_file(..., driver="KML")`).
3. For ZIP, the archive is extracted to a temp directory, the first `.shp` is located, and that path is read.
4. Any read failure (bad file, ZIP with no shapefile, unreadable `.shp`) comes back as `400`: `gpd.read_file` errors are caught and converted into a clean error message instead of a crash.
5. The GeoDataFrame is cached in `files_db` under a fresh UUID along with filename, feature count, CRS string, and `status: "COMPLETED"`.

**Measurement flow** (`GET /api/files/{id}/measurements/`):

1. Each row of the cached GeoDataFrame becomes one `FeatureResponse`.
2. `_geodesic()` prepares the geometry (see below), then `pyproj.Geod` measures it:
   - `geod.geometry_area_perimeter(geom)[0]` → geodesic area on the WGS84 ellipsoid (absolute value, since the sign encodes winding).
   - `geod.geometry_length(geom)` → geodesic length in metres.
3. Per-feature exceptions become `FAILED` instead of failing the whole request.
4. Attribute columns are filtered with `_is_missing()` (which uses `pd.isna`) so NaN / NaT values don't leak into JSON, then attached alongside the GeoJSON geometry.

**Antimeridian handling.** The catch: a compact polygon that straddles the ±180° seam (say Fiji, whose ring goes `179 → -178.5`) gets measured the "long way around" if you just throw it at Geod, which massively overstates the area. `_geodesic()` looks for this: it computes the *occupied* longitude span (from the largest gap between the sorted longitudes) and, when the raw span is > 180° but the occupied span is ≤ 180°, it shifts the negative longitudes by +360° and measures the shifted copy. Shifting longitude is an isometry on the sphere, so area and length stay the same. Genuinely wide features (occupied span > 180°, like Russia) are measured as-is. Files that come in a projected CRS get converted to EPSG:4326 first.

## 6. Design Decisions and Testing Journey

This section is the real development log: what broke, what it taught me, and how each fix was verified.

### KML timestamps: the `NaT` crash

The first real bug came up while running a measurement test against actual KML. GeoPandas reads KML through pyogrio, which adds `timestamp` / `begin` / `end` columns. On features that don't have those times, the values are pandas `NaT` (not-a-time) objects. The original `properties` filter only stripped `None` and float NaN, so `NaT` slipped through. The moment Pydantic tried to serialize it, the endpoint threw a `PydanticSerializationError`.

The fix was `_is_missing()`, a small wrapper around `pd.isna()` that also catches the `TypeError`/`ValueError` cases for values pandas can't handle, and it drops every missing value from `properties`. This was one of those bugs only tests can catch: the upload succeeded, the DataFrame looked fine, and nothing blew up until JSON serialization.

### Geometry measurement checks

The basic question was just "can we measure this geometry?" and I settled on four statuses:

- `SUCCESS`: the geometry was measured,
- `FAILED`: measurement raised,
- `NOT_REQUIRED`: points (and empty/null geometries),
- `UNSUPPORTED`: anything else.

Explicit statuses instead of crashing or silently skipping came out of testing small KML fixtures with a polygon, a line, and a point together. The point has to be reported, not errored, and one bad feature must not sink the entire response.

### The CRS problem with the country dataset

Running the full Admin 0 dataset was the turning point. The first implementation projected everything into a single UTM zone picked by `estimate_utm_crs()`. That failed at global scale: it spat out `RuntimeWarning: invalid value encountered in area`, gave Australia 15.3 M km² (real ≈ 7.69), USA 10.7 (real ≈ 9.83), Russia 19.0 (real ≈ 17.1), and Antarctica 4.7 (real ≈ 14). Two separate causes:

- one UTM zone for the whole planet means almost every country sits outside its sweet spot;
- seam-straddlers like Fiji get "shattered" across ±180°, so their polygons tear open.

The fix was to stop projecting altogether: `pyproj.Geod(ellps="WGS84")` computes area and length directly on the ellipsoid, and it carries the seam handling from §5 along with it. After the rewrite, the same dataset measured Australia 7.688, USA 9.511, Russia 17.019, Antarctica 12.336, Brazil 8.509 M km² with zero warnings, lining up well with published values (Antarctica's gap is expected, since the 110m dataset draws the coastline well south of some reference figures).

Honest caveat: geodesic measurements are still approximations of true surface area, and the seam-shift heuristic assumes a compact straddler rather than a genuinely wide feature. Passing tests show the code does what I designed for the covered cases, not that every real-world polygon is exact.

### Regression tests

The suite grew to **13 passing tests** (`test_api.py`): health check, KML and ZIP uploads, metadata, 404s, invalid-file rejection, and per-geometry measurement statuses. Two were added specifically to lock in the CRS work:

- `test_measurements_antimeridian_polygon`: a Fiji-shaped polygon spanning `179° → -178.5°` must measure ≈ `6.15430e10` m² (the compact seam-crosser case).
- `test_measurements_wide_global_band`: a band 150° wide across Europe/Asia must measure ≈ `4.78891e12` m² (the genuinely-wide case, no shift).

Without the seam detection, the first test would report millions of extra square kilometres; without the occupied-span check, the second one would get distorted by an unnecessary shift.

## 7. Learning and Experience

- **FastAPI endpoint testing.** Pushing the real app through `TestClient` (instead of just calling functions) is what caught the `NaT` serialization bug that simple inspection missed. Uploading fixtures as `files={"file": (name, data, ...)}` is basically what a real client sends.
- **GeoPandas processing.** Reading KML from `BytesIO` but ZIPs from an extracted temp file taught me that formats have different IO quirks. Checking extensions, extracting into a temp dir, and picking the first `.shp` were all small but real parsing decisions.
- **Shapely geometries.** Matching on `geom_type` (`Polygon`, `LineString`, `Point`, …) and treating empty/null geometry separately from unsupported types shaped the response model. You have to handle every geometry type explicitly, there is no catch-all, which is why the `Point`/`MultiPoint` → `NOT_REQUIRED` and "everything else" → `UNSUPPORTED` branches are deliberate.
- **Geodesic measurement.** `Geod.geometry_area_perimeter()` and `Geod.geometry_length()` made projection-free measurements possible, but the seam problem (171°→-178° ring) showed that "just use geodesics" isn't a silver bullet either; you still have to care about how coordinates wrap around.
- **Missing property values.** `None`, float `NaN`, and pandas `NaT` are all "missing", yet they serialize (and fail) differently. One `pd.isna`-wrapped predicate handled all of them.
- **Error handling.** Catching at the right layer, upload errors as 400 and measurement errors as per-feature `FAILED`, keeps one bad feature or one malformed file from taking the whole API down. The `except HTTPException: raise` pass-through keeps controlled errors distinct from unexpected ones.

## 8. Future Scope

Ideas that go beyond what's built today (kept clearly separate from current behavior):

- **Persistence.** `files_db` is an in-memory dict, so every uploaded file disappears on restart. Swapping in SQLite or object storage (S3) would make the API actually usable.
- **Uvicorn workers / async.** The app is trivially concurrent but `gpd.read_file` is synchronous, so a worker pool or uvicorn with workers would help under load.
- **A real upload-size policy and file-type sniffing.** Extension checks plus parse-time errors work fine, but sniffing magic bytes / content-type and capping upload size would harden it.
- **More geometry outputs.** Perimeter (Geod computes it internally but we don't return it), centroid, and bounding-box could be exposed next to area/length.
- **Handling multi-file ZIPs.** Only the first `.shp` gets read; supporting multiple shapefiles per archive (or letting the client pick) is the natural next step.
- **Better seam coverage.** The shift heuristic covers compact straddlers; a more general strategy (like feature-wise antimeridian repair in data pipelines) would handle exotic real-world datasets.
- **CI.** A small GitHub Actions job running `pytest` on every push would protect the 13 tests (and the CRS behavior they lock in).