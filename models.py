from typing import Any
from pydantic import BaseModel

class Measurement(BaseModel):
    area: float | None = None
    area_unit: str | None = None
    length: float | None = None
    length_unit: str | None = None
    status: str

class FeatureResponse(BaseModel):
    id: str
    geometry_type: str
    geometry: dict[str, Any]
    crs: str | None
    properties: dict[str, Any]
    measurement: Measurement

class FileResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: str


class MeasurementsResponse(BaseModel):
    file_id: str
    measurements: list[FeatureResponse]