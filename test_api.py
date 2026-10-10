import io
import zipfile

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from main import app

client = TestClient(app)

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>poly</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        0,0,0 1,0,0 1,1,0 0,1,0 0,0,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark><name>line</name>
      <LineString><coordinates>0,0,0 1,1,0</coordinates></LineString>
    </Placemark>
    <Placemark><name>pt</name>
      <Point><coordinates>0.5,0.5,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""


def _upload(name: str, data: bytes):
    return client.post(
        "/api/files/",
        files={"file": (name, data, "application/octet-stream")},
    )


@pytest.fixture(scope="module")
def kml_id():
    r = _upload("shapes.kml", KML.encode())
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def zip_bytes():
    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(2, 2), (3, 2), (3, 3)]),
        ],
        crs="EPSG:4326",
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        with __import__("tempfile").TemporaryDirectory() as tmp:
            gdf.to_file(f"{tmp}/shapes.shp")
            for f in ("shp", "shx", "dbf", "prj", "cpg"):
                try:
                    z.write(f"{tmp}/shapes.{f}", f"shapes.{f}")
                except FileNotFoundError:
                    pass
    return buf.getvalue()


def test_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "API is Active."


def test_upload_kml(kml_id):
    r = client.get(f"/api/files/{kml_id}/")
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "shapes.kml"
    assert body["feature_count"] == 3
    assert body["status"] == "COMPLETED"


def test_get_file_not_found():
    assert client.get("/api/files/nope/").status_code == 404


def test_measurements_polygon_area(kml_id):
    r = client.get(f"/api/files/{kml_id}/measurements/")
    assert r.status_code == 200
    feats = {f["geometry_type"]: f for f in r.json()["measurements"]}
    poly = feats["Polygon"]["measurement"]
    assert poly["status"] == "SUCCESS"
    assert poly["area"] > 0
    assert poly["area_unit"] == "m²"


def test_measurements_line_length(kml_id):
    r = client.get(f"/api/files/{kml_id}/measurements/")
    feats = {f["geometry_type"]: f for f in r.json()["measurements"]}
    line = feats["LineString"]["measurement"]
    assert line["status"] == "SUCCESS"
    assert line["length"] > 0
    assert line["length_unit"] == "m"


def test_measurements_point(kml_id):
    r = client.get(f"/api/files/{kml_id}/measurements/")
    feats = {f["geometry_type"]: f for f in r.json()["measurements"]}
    assert feats["Point"]["measurement"]["status"] == "NOT_REQUIRED"


def test_measurements_file_not_found():
    assert client.get("/api/files/nope/measurements/").status_code == 404


def test_upload_zip(zip_bytes):
    r = _upload("shapes.zip", zip_bytes)
    assert r.status_code == 200, r.text
    assert r.json()["feature_count"] == 2


def test_upload_invalid_extension():
    r = _upload("notes.txt", b"hello")
    assert r.status_code == 400


def test_upload_bad_kml():
    r = _upload("bad.kml", b"not really kml")
    assert r.status_code == 400


def test_upload_zip_without_shapefile():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "nothing")
    r = _upload("empty.zip", buf.getvalue())
    assert r.status_code == 400


def _kml_polygon(coords: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        {coords}
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
  </Document>
</kml>
"""


def _upload_polygon_measurement(coords: str) -> dict:
    r = _upload("poly.kml", _kml_polygon(coords).encode())
    assert r.status_code == 200, r.text
    m = client.get(f"/api/files/{r.json()['id']}/measurements/")
    return m.json()["measurements"][0]["measurement"]


def test_measurements_antimeridian_polygon():
    measurement = _upload_polygon_measurement(
        "179,0 179,2 -178.5,2 -178.5,0 179,0"
    )
    assert measurement["status"] == "SUCCESS"
    assert abs(measurement["area"] - 6.15430e10) < 1e6


def test_measurements_wide_global_band():
    measurement = _upload_polygon_measurement(
        "30,50 30,70 180,70 180,50 30,50"
    )
    assert measurement["status"] == "SUCCESS"
    assert abs(measurement["area"] - 4.78891e12) < 1e8
