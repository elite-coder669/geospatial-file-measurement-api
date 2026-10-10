from fastapi import FastAPI
from app import router

app = FastAPI(title="Aereo Geospatial API")

app.include_router(router)