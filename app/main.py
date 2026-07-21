import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from auth import router as auth_router
from db import get_conn


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
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}
