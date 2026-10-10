1. First step is to make an API entry point.
2. second we need shapefiles / KML files or both to determine the exact payload for API.
3. Downloaded Natural Earth Dataset(ADMIN 0) for designing API and Analysis.
4. Wrote the FastAPI app with 4 main endpoints: health check, file upload (KML/ZIP), file metadata, and measurements per feature.
5. Started writing a minimal test suite with FastAPI TestClient so the API is tested the way a real client would call it, not just through direct function calls.
6. First test run exposed a crash: real KML files have timestamp/begin/end columns that come back as pandas NaT. The old filter only removed None and float NaN, so NaT leaked into JSON and Pydantic blew up with a serialization error. Fixed it with a small _is_missing() helper that wraps pd.isna.
7. Then came geometry measurement. Settled on 4 statuses instead of crashing: SUCCESS, FAILED, NOT_REQUIRED for points, UNSUPPORTED for everything else. One bad feature must not sink the whole response.
8. The country dataset (Natural Earth Admin 0) exposed the real CRS problem. Projecting everything to one UTM zone gave garbage at global scale: Australia 15.3 instead of 7.69, warnings about invalid area values, and Fiji got shattered across the antimeridian.
9. Switched to pyproj.Geod for pure geodesic measurements on the WGS84 ellipsoid, no projection at all. Then found the seam problem: a compact polygon crossing 180 degrees (like Fiji, 179 to -178.5) gets measured the long way around. Added a heuristic that computes the occupied longitude span and, only for compact antimeridian-crossing polygons, shifts negative longitudes by +360 to measure the shifted copy. It's a heuristic, not a universal solution, so exotic geometries could still break it. Wide features like Russia are measured as-is.
10. Final numbers with the geodesic approach on the full dataset: Australia 7.688, USA 9.511, Russia 17.019, Antarctica 12.336, Brazil 8.509, zero warnings. All 177 countries SUCCESS.
11. Added 2 regression tests to lock the CRS behavior: one antimeridian polygon and one wide global band. Test suite now has 13 passing tests.
12. GeoPandas reads KML from BytesIO but ZIPs need the first .shp extracted to a temp dir first. Different formats, different IO handling.
13. Wrote the README documenting the whole journey and wrote this notes file as I went. The dataset is only for testing; the API runs on whatever file you upload. 

