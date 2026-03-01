"""
KoTH CTF Platform — Main Application
King of the Hill CTF Scoreboard API
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.database import engine, init_db
from app.services.tick_engine import tick_engine
from app.services.ws_manager import ws_manager
from app.routers import scoreboard, teams, hills, admin, websocket, internal, registration, auth, agent, vpn

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("koth.main")

settings = get_settings()
start_time = time.time()


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown"""
    logger.info("=" * 60)
    logger.info("KoTH CTF Platform")
    logger.info("King of the Hill - Scoreboard API")
    logger.info("=" * 60)

    # Init DB connection pool
    await init_db()
    logger.info("Database connection pool initialised")

    # Init Redis
    try:
        app.state.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
        await app.state.redis.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        app.state.redis = None

    # Wire WebSocket broadcast into tick engine
    tick_engine.set_ws_callback(ws_manager.broadcast_all)

    # Wire Redis into tick engine for agent report lookups
    tick_engine.set_redis(app.state.redis)

    # Restore tick engine state from DB (survives container restart)
    try:
        from app.database import async_session
        async with async_session() as db:
            await tick_engine.load_config(db)
        logger.info(
            f"Tick engine state restored: status={'running' if tick_engine.is_running and not tick_engine.is_paused else 'paused' if tick_engine.is_paused else 'not_started'}, "
            f"tick={tick_engine.current_tick}, start_time={tick_engine.game_start_time}"
        )
        # Auto-resume game loop if game was running
        if tick_engine.is_running and not tick_engine.is_paused:
            tick_engine._task = asyncio.create_task(tick_engine._game_loop())
            logger.info("Game loop auto-resumed after restart")
        elif tick_engine.is_running and tick_engine.is_paused:
            logger.info("Game is paused — not auto-resuming loop")
    except Exception as e:
        logger.warning(f"Failed to restore tick engine state: {e}")

    logger.info("Scoreboard API ready ✓")

    yield  # ── app is running ──

    # Shutdown
    logger.info("Shutting down...")
    if tick_engine.is_running:
        await tick_engine.stop()
    if app.state.redis:
        await app.state.redis.close()
    await engine.dispose()
    logger.info("Shutdown complete")


# ─── Application ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="KoTH CTF Platform",
    description="King of the Hill CTF Scoreboard & Game Engine",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Request timing middleware ───────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.time() - t0:.4f}"
    return response


# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(scoreboard.router)
app.include_router(teams.router)
app.include_router(hills.router)
app.include_router(admin.router)
app.include_router(websocket.router)
app.include_router(internal.router)
app.include_router(registration.router)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(vpn.router)


# ─── Static files (frontend) ────────────────────────────────────────────────
import os
from pathlib import Path
from fastapi.responses import FileResponse, RedirectResponse

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")

# Redirect /static/*.html → clean URL so users never see /static/ in browser
_HTML_TO_CLEAN = {
    "login.html": "/login",
    "register.html": "/register",
    "dashboard.html": "/dashboard",
    "organizer.html": "/organizer",
    "admin.html": "/admin",
    "index.html": "/scoreboard",
    "history.html": "/history",
}


@app.middleware("http")
async def redirect_static_html(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static/") and path.endswith(".html"):
        filename = path.split("/")[-1]
        clean_url = _HTML_TO_CLEAN.get(filename)
        if clean_url:
            return RedirectResponse(url=clean_url, status_code=301)
    return await call_next(request)


if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ─── Friendly URL routes (serve static HTML for clean paths) ────────────────
_STATIC_DIR = Path(static_dir).resolve() if os.path.isdir(static_dir) else None

# Public pages (no server-side auth required — admin pages have their own
# client-side auth overlay that prompts for admin token before showing content)
_PUBLIC_PAGES = {
    "/login": "login.html",
    "/register": "register.html",
    "/dashboard": "dashboard.html",
    "/vpn": "dashboard.html",
    "/topology": "dashboard.html",
    "/rules": "dashboard.html",
    "/guide": "dashboard.html",
    "/scoreboard": "index.html",
    "/history": "history.html",
    "/organizer": "organizer.html",
    "/admin": "admin.html",
}


def _make_public_handler(filename: str):
    async def _handler():
        if _STATIC_DIR and (_STATIC_DIR / filename).is_file():
            return FileResponse(_STATIC_DIR / filename, media_type="text/html")
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)
    return _handler


for _path, _file in _PUBLIC_PAGES.items():
    app.get(_path, include_in_schema=False)(_make_public_handler(_file))


# ─── Root ────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    if _STATIC_DIR and (_STATIC_DIR / "login.html").is_file():
        return FileResponse(_STATIC_DIR / "login.html", media_type="text/html")
    return HTMLResponse(
        content="""
        <html><head>
            <meta http-equiv="refresh" content="0; url=/login" />
        </head><body>
            <p>Redirecting to login...</p>
        </body></html>
        """
    )


# ─── Health ──────────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check(request: Request):
    db_ok = False
    redis_ok = False

    try:
        from sqlalchemy import text
        from app.database import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    try:
        if request.app.state.redis:
            await request.app.state.redis.ping()
            redis_ok = True
    except Exception:
        pass

    uptime = time.time() - start_time
    game_status = tick_engine.get_status()

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "db_connected": db_ok,
        "redis_connected": redis_ok,
        "game_status": game_status["status"],
        "uptime_seconds": round(uptime, 1),
        "ws_connections": ws_manager.connection_count,
    }
