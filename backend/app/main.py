from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
import contextlib

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar Base de datos al arrancar
    await init_db()
    yield
    # Clean up (si es necesario) al apagar

app = FastAPI(
    title="QUANTEX API",
    description="Algorithmic Trading Platform API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to QUANTEX API", "status": "online"}

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

from app.api import bots
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])

from app.api import public
app.include_router(public.router, prefix="/api/public", tags=["public"])
