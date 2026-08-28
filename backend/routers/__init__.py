# Expose routers for `backend.main`.
# IMPORTANT: many routers import `core.*` (not `backend.core.*`), so ensure
# the backend folder is on sys.path before importing them.
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from .auth import router as auth_router
from .query import router as query_router
from .ingest import router as ingest_router
from .social import router as social_router
from .reports import router as reports_router
from .search import router as search_router
from .brands import router as brands_router
from .companies import router as companies_router
from .campaigns import router as campaigns_router
from .notifications import router as notifications_router


