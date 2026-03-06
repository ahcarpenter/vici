from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.exceptions import twilio_signature_invalid_handler
from src.sms.exceptions import TwilioSignatureInvalid
from src.sms.router import router as sms_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OTel and structlog initialization in Plan 03
    yield


app = FastAPI(lifespan=lifespan)

app.add_exception_handler(TwilioSignatureInvalid, twilio_signature_invalid_handler)

app.include_router(sms_router)


@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception:
        return JSONResponse(
            status_code=200,
            content={"status": "degraded", "db": "error"},
        )
