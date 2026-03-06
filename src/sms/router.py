from fastapi import APIRouter

router = APIRouter(prefix="/webhook", tags=["sms"])
# POST /sms route implemented in Plan 02
