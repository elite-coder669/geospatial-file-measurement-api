from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from fastapi import APIRouter, UploadFile, File, HTTPException
from pyproj import Geod

from models import FileResponse, FeatureResponse, Measurement, MeasurementsResponse

router = APIRouter()
files_db = {}

_GEOD = Geod(ellps="WGS84")


def _is_missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _longitude_span(geometry):
    lons = shapely.get_coordinates(geometry)[:, 0] % 360.0
    ordered = np.sort(np.unique(lons))
    gaps = np.diff(ordered)
    gaps = np.append(gaps, ordered[0] + 360.0 - ordered[-1])
    return 360.0 - float(gaps.max())


def _geodesic(geometry, source_crs):
    if source_crs is not None and not source_crs.is_geographic:
        geometry = (
            gpd.GeoSeries([geometry], crs=source_crs)
            .to_crs("EPSG:4326")
            .iloc[0]
        )

    lons = shapely.get_coordinates(geometry)[:, 0]
    if (
        float(lons.max() - lons.min()) > 180.0
        and _longitude_span(geometry) <= 180.0
    ):
        geometry = shapely.transform(
            geometry,
            lambda c: np.column_stack(
                (np.where(c[:, 0] < 0, c[:, 0] + 360.0, c[:, 0]), c[:, 1])
            ),
            include_z=False,
        )

    return geometry


@router.get("/")
def health():
    return {"status": "API is Active."}


@router.post("/api/files/", response_model=FileResponse)
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or ""

    if not filename.lower().endswith((".kml", ".zip")):
        raise HTTPException(400, "Only KML and ZIP files are supported")

    content = await file.read()

    try:
        if filename.lower().endswith(".kml"):
            gdf = gpd.read_file(BytesIO(content), driver="KML")
        else:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                shp_files = [
                    name for name in archive.namelist()
                    if name.lower().endswith(".shp")
                ]

                if not shp_files:
                    raise HTTPException(400, "ZIP contains no Shapefile")

                with TemporaryDirectory() as temp_dir:
                    archive.extractall(temp_dir)
                    shp_path = Path(temp_dir) / shp_files[0]
                    gdf = gpd.read_file(shp_path)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "Unable to read geospatial file") from exc

    file_id = str(uuid4())

    files_db[file_id] = {
        "id": file_id,
        "filename": filename,
        "feature_count": len(gdf),
        "crs": str(gdf.crs) if gdf.crs else None,
        "status": "COMPLETED",
        "gdf": gdf,
    }

    return FileResponse(
        id=file_id,
        filename=filename,
        feature_count=len(gdf),
        crs=str(gdf.crs) if gdf.crs else None,
        status="COMPLETED",
    )


@router.get("/api/files/{file_id}/", response_model=FileResponse)
def get_file(file_id: str):
    data = files_db.get(file_id)

    if not data:
        raise HTTPException(404, "File not found")

    return FileResponse(
        id=data["id"],
        filename=data["filename"],
        feature_count=data["feature_count"],
        crs=data["crs"],
        status=data["status"],
    )


@router.get(
    "/api/files/{file_id}/measurements/",
    response_model=MeasurementsResponse,
)
def get_measurements(file_id: str):
    data = files_db.get(file_id)

    if not data:
        raise HTTPException(404, "File not found")

    gdf = data["gdf"]
    features = []

    for index, row in gdf.iterrows():
        geometry = row.geometry
        measurement = Measurement(status="NOT_REQUIRED")

        if geometry is not None and not geometry.is_empty:
            if geometry.geom_type in ("Polygon", "MultiPolygon"):
                try:
                    measured = _geodesic(geometry, gdf.crs)
                    area = abs(_GEOD.geometry_area_perimeter(measured)[0])

                    measurement = Measurement(
                        area=area,
                        area_unit="m²",
                        status="SUCCESS",
                    )
                except Exception:
                    measurement = Measurement(status="FAILED")

            elif geometry.geom_type in ("LineString", "MultiLineString"):
                try:
                    measured = _geodesic(geometry, gdf.crs)
                    length = _GEOD.geometry_length(measured)

                    measurement = Measurement(
                        length=length,
                        length_unit="m",
                        status="SUCCESS",
                    )
                except Exception:
                    measurement = Measurement(status="FAILED")

            elif geometry.geom_type not in ("Point", "MultiPoint"):
                measurement = Measurement(status="UNSUPPORTED")

        properties = row.drop(labels=[gdf.geometry.name]).to_dict()
        properties = {
            key: value
            for key, value in properties.items()
            if not _is_missing(value)
        }

        features.append(
            FeatureResponse(
                id=str(index),
                geometry_type=geometry.geom_type if geometry else "Unknown",
                geometry=geometry.__geo_interface__ if geometry else {},
                crs=data["crs"],
                properties=properties,
                measurement=measurement,
            )
        )

    return MeasurementsResponse(
        file_id=file_id,
        measurements=features,
    )