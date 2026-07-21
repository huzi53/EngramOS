import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import router as auth_router
from capture import router as capture_router
from db import get_conn
from embed import _get_model
from search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Upsert the single user from env secrets; DB stays source of truth for users.id.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            """,
            (os.environ["AUTH_USERNAME"], os.environ["AUTH_PASSWORD_HASH"]),
        )
        conn.commit()
    _get_model()  # warm the embedding model so the first capture doesn't eat the load time
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(capture_router)
app.include_router(search_router)


@app.get("/health")
def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}


# Mounted last so /health and /api/v1/* above take precedence over the catch-all "/".
app.mount("/", StaticFiles(directory="static", html=True))
