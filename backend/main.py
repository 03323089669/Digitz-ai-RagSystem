import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ==========================================================
# Python Import Paths
# ==========================================================

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ==========================================================
# Routers
# ==========================================================

from routers import (
    admin,
    analytics,
    auth,
    brands,
    campaigns,
    companies,
    conversations,
    ingest,
    notifications,
    query,
    reports,
    search,
    settings,
    social,
    users,
)

from core.db import init_db, get_users
from core.cache import get_cache_stats

# ==========================================================
# FastAPI App
# ==========================================================

app = FastAPI(
    title="Digitz AI Backend",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ==========================================================
# CORS
# ==========================================================

# Allow localhost dev + any additional ports (Vite may use different port).
# If you deploy, replace with explicit production origins.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ==========================================================
# Startup
# ==========================================================

@app.on_event("startup")
async def startup():
    print("[Digitz AI] Initializing database...")
    init_db()
    print("[Digitz AI] Database ready ✓")

# ==========================================================
# Register Routers
# ==========================================================

app.include_router(auth.router)
app.include_router(brands.router)
app.include_router(companies.router)
app.include_router(campaigns.router)
app.include_router(ingest.router)
app.include_router(notifications.router)
app.include_router(query.router)
app.include_router(reports.router)
app.include_router(search.router)
app.include_router(social.router)
app.include_router(conversations.router)
app.include_router(settings.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(users.router)

# ==========================================================
# Health Endpoints
# ==========================================================

@app.get("/")
async def root():
    return {
        "success": True,
        "message": "Digitz AI Backend Running 🚀",
        "version": "2.0.0",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


@app.get("/status")
async def status():
    return {
        "status": "running",
        "backend": "online",
    }


@app.get("/debug/users")
async def debug_users():
    return {
        "count": len(get_users()),
        "users": get_users(),
    }


@app.get("/debug/cache")
async def debug_cache():
    """View cache performance stats."""
    return get_cache_stats()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)