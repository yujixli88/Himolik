"""Himolik — виртуальная лаборатория по химии и физике с ИИ-лаборантом (FastAPI).

Запуск локально:   uvicorn main:app --reload
Запуск на Render:  uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import catalog, rooms, simulator
from app.ai import GeminiClient, LabContext
from app.config import settings
from app.qr import make_qr_svg
from app.security import (Claims, RateLimiter, clean_name, clean_title, sign_token, valid_code,
                          verify_token)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # не писать адреса запросов в логи
log = logging.getLogger("himolik")

STATIC_DIR = Path(__file__).resolve().parent / "static"

store = rooms.RoomStore()
limiter = RateLimiter()
gemini = GeminiClient()


# =============================================================================
# Запуск / остановка
# =============================================================================
async def _janitor() -> None:
    while True:
        await asyncio.sleep(300)
        store.purge()
        limiter.cleanup()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.warn_about_problems()
    task = asyncio.create_task(_janitor())
    yield
    task.cancel()
    await gemini.aclose()


app = FastAPI(
    title="Himolik",
    lifespan=lifespan,
    # Описание API не публикуем в продакшене.
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)


# =============================================================================
# Ошибки и заголовки безопасности
# =============================================================================
class ApiError(Exception):
    def __init__(self, status: int, code: str, **extra):
        self.status, self.code, self.extra = status, code, extra


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse({"error": exc.code, **exc.extra}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, __: RequestValidationError):
    return JSONResponse({"error": "bad_request"}, status_code=422)  # подробности наружу не отдаём


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": "not_found" if exc.status_code == 404 else "http_error"},
                        status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.error("Необработанная ошибка: %s", type(exc).__name__)
    return JSONResponse({"error": "server_error"}, status_code=500)


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_body_bytes:
        return JSONResponse({"error": "too_large"}, status_code=413)
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "no-referrer"
    h["X-Frame-Options"] = "DENY"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    h["Strict-Transport-Security"] = "max-age=31536000"
    if not settings.debug:
        h["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    return response


# =============================================================================
# Вспомогательное
# =============================================================================
def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit(key: str, count: int, window: float) -> None:
    ok, retry = limiter.hit(key, count, window)
    if not ok:
        raise ApiError(429, "rate_limited", retry_after=retry)


def base_url(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


def _gone_or_missing(code: str) -> ApiError:
    if store.was_closed(code):
        return ApiError(410, "room_closed")
    return ApiError(404, "room_not_found")


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized")
    return authorization[7:].strip()


async def teacher_claims(authorization: str | None = Header(default=None)) -> Claims:
    claims = verify_token(_bearer(authorization))
    if claims is None or claims.role != "t":
        raise ApiError(401, "unauthorized")
    return claims


async def teacher_room(claims: Claims = Depends(teacher_claims)) -> rooms.Room:
    room = store.get(claims.code)
    if room is None:
        raise _gone_or_missing(claims.code)
    rooms.touch(room)
    return room


async def student_ctx(authorization: str | None = Header(default=None)):
    claims = verify_token(_bearer(authorization))
    if claims is None or claims.role != "s":
        raise ApiError(401, "unauthorized")
    room = store.get(claims.code)
    if room is None:
        raise _gone_or_missing(claims.code)
    student = room.students.get(claims.sid)
    if student is None:
        raise ApiError(404, "student_not_found")
    rooms.touch(room, student)
    return room, student


def teacher_payload(room: rooms.Room, request: Request) -> dict:
    return {
        "code": room.code,
        "token": sign_token("t", room.code),
        "subject": room.subject,
        "title": room.title,
        "items": room.items,
        "join_url": f"{base_url(request)}/?room={room.code}",
    }


def student_payload(room: rooms.Room, student: rooms.Student, token: str | None = None) -> dict:
    ev = simulator.evaluate(room.subject, student.state)
    found, total = rooms.progress(room, student)
    out = {
        "student": {"id": student.id, "name": student.name},
        "room": {"code": room.code, "subject": room.subject, "title": room.title, "items": room.items},
        "state": ev["view"],
        "snapshot": student.state,
        "found": found,
        "total": total,
    }
    if token:
        out["token"] = token
    return out


# =============================================================================
# Модели запросов
# =============================================================================
class CreateRoomBody(BaseModel):
    subject: Literal["chemistry", "physics"]
    title: str = Field(min_length=1, max_length=120)
    items: list[str] = Field(min_length=1, max_length=20)


class JoinBody(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    name: str = Field(min_length=1, max_length=60)
    token: str | None = Field(default=None, max_length=200)   # прежний токен (повторный вход)
    snapshot: dict | None = None                               # снимок опыта (после перезапуска сервера)
    found: list[str] = Field(default_factory=list, max_length=60)


class ActBody(BaseModel):
    action: Literal["add", "remove", "reset", "toggle"]
    item: str | None = Field(default=None, max_length=30)
    index: int | None = Field(default=None, ge=0, le=50)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=settings.chat_max_chars)
    lang: Literal["ru", "kk"] = "ru"


# =============================================================================
# Публичные эндпоинты
# =============================================================================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.get("/api/catalog")
async def get_catalog():
    return catalog.public_catalog(settings.assistant_name)


@app.get("/api/rooms/{code}/qr.svg")
async def room_qr(code: str, request: Request):
    if not valid_code(code):
        raise ApiError(404, "not_found")
    limit(f"qr:{client_ip(request)}", 60, 60)
    try:
        svg = make_qr_svg(f"{base_url(request)}/?room={code}")
    except Exception as exc:  # segno не установлен и т. п. — на странице останется ссылка
        log.error("QR не создан: %s", type(exc).__name__)
        raise ApiError(503, "qr_unavailable")
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


# =============================================================================
# Учитель
# =============================================================================
@app.post("/api/rooms")
async def create_room(body: CreateRoomBody, request: Request):
    limit(f"create:{client_ip(request)}", 10, 600)
    items = catalog.validate_items(body.subject, body.items)
    title = clean_title(body.title)
    if not items or not title:
        raise ApiError(400, "bad_request")
    try:
        room = store.create(body.subject, title, items)
    except rooms.StoreFull:
        raise ApiError(503, "server_busy")
    return teacher_payload(room, request)


@app.post("/api/teacher/restore")
async def restore_room(body: CreateRoomBody, request: Request, claims: Claims = Depends(teacher_claims)):
    """Воскрешает комнату с тем же кодом после перезапуска сервера (токен подписан, подделать нельзя)."""
    if store.was_closed(claims.code):
        raise ApiError(410, "room_closed")
    room = store.get(claims.code)
    if room is None:
        items = catalog.validate_items(body.subject, body.items)
        title = clean_title(body.title)
        if not items or not title:
            raise ApiError(400, "bad_request")
        try:
            room = store.create(body.subject, title, items, code=claims.code)
        except rooms.StoreFull:
            raise ApiError(503, "server_busy")
    rooms.touch(room)
    return teacher_payload(room, request)


@app.get("/api/teacher/room")
async def teacher_state(request: Request, room: rooms.Room = Depends(teacher_room)):
    out = teacher_payload(room, request)
    out.pop("token")
    out["students"] = rooms.teacher_summary(room)
    return out


@app.get("/api/teacher/students/{sid}/chat")
async def teacher_student_chat(sid: str, room: rooms.Room = Depends(teacher_room)):
    student = room.students.get(sid)
    if student is None:
        raise ApiError(404, "student_not_found")
    return {"name": student.name, "log": student.log}


@app.delete("/api/teacher/room")
async def close_room(room: rooms.Room = Depends(teacher_room)):
    store.close(room.code)
    return {"ok": True}


# =============================================================================
# Ученик
# =============================================================================
@app.post("/api/join")
async def join(body: JoinBody, request: Request):
    ip = client_ip(request)
    limit(f"join:{ip}", 90, 60)  # запас: в классе все ученики за одним школьным IP
    fail_key = f"joinfail:{ip}"
    if limiter.count(fail_key, 300) >= 30:  # защита от перебора кодов
        raise ApiError(429, "rate_limited", retry_after=60)

    code = body.code.strip()
    if not valid_code(code):
        limiter.add(fail_key)
        raise ApiError(400, "bad_code")
    if store.was_closed(code):
        raise ApiError(410, "room_closed")
    room = store.get(code)
    if room is None:
        limiter.add(fail_key)
        raise ApiError(404, "room_not_found")
    name = clean_name(body.name)
    if not name:
        raise ApiError(400, "bad_name")

    student, sid = None, None
    claims = verify_token(body.token) if body.token else None
    if claims and claims.role == "s" and claims.code == code:
        sid = claims.sid
        student = room.students.get(sid)
    if student is None:
        try:
            student = store.add_student(room, name, sid)
        except rooms.RoomFull:
            raise ApiError(409, "room_full")
        if body.snapshot is not None:
            student.state, found = simulator.replay(room.subject, body.snapshot, room.items)
            student.discovered |= found
        for eid in body.found:
            ev = catalog.EVENTS.get(eid)
            if ev and ev["subject"] == room.subject:
                student.discovered.add(eid)
    rooms.touch(room, student)
    return student_payload(room, student, token=sign_token("s", code, student.id))


@app.get("/api/me")
async def me(ctx=Depends(student_ctx)):
    room, student = ctx
    return student_payload(room, student)


@app.post("/api/act")
async def act(body: ActBody, ctx=Depends(student_ctx)):
    room, student = ctx
    limit(f"act:{student.id}", 120, 60)
    prev = simulator.evaluate(room.subject, student.state)
    new_state, err = simulator.apply_action(room.subject, student.state, body.action,
                                            body.item, body.index, room.items)
    if err:
        raise ApiError(400, err)
    student.state = new_state
    cur = simulator.evaluate(room.subject, new_state)
    events = simulator.new_events(room.subject, prev, cur)
    student.discovered.update(events)
    student.recent_events.extend(events)
    student.actions += 1
    found, total = rooms.progress(room, student)
    return {"state": cur["view"], "snapshot": new_state, "events": events, "found": found, "total": total}


@app.post("/api/chat")
async def chat(body: ChatBody, ctx=Depends(student_ctx)):
    room, student = ctx
    question = " ".join(body.message.split())
    if not question:
        raise ApiError(400, "bad_request")
    limit(f"chat-min:{student.id}", settings.chat_per_student_per_min, 60)
    limit(f"chat-hour:{student.id}", settings.chat_per_student_per_hour, 3600)
    limit(f"chat-room:{room.code}", settings.chat_per_room_per_min, 60)

    # Контекст опыта строит сервер по состоянию симулятора — клиент его подменить не может.
    ev = simulator.evaluate(room.subject, student.state)
    lab = LabContext(
        subject=room.subject,
        title=room.title,
        items_ru=[catalog.ITEMS[i]["ai"] for i in room.items],
        state_desc=simulator.describe_ru(room.subject, ev),
        recent_ru=[catalog.EVENTS[e]["ru"] for e in student.recent_events if e in catalog.EVENTS],
    )
    result = await gemini.ask(lab, student.history, question, body.lang)

    if result.source == "busy":
        raise ApiError(429, "ai_busy", message=result.answer, retry_after=10)
    if result.source == "unavailable":
        raise ApiError(503, "ai_unavailable", message=result.answer)

    student.questions += 1
    if result.on_topic:
        student.history = (student.history + [("user", question), ("model", result.answer)])[-8:]
    else:
        student.off_topic += 1  # отказы в контекст модели не попадают
    student.log = (student.log + [{"t": int(time.time()), "q": question, "a": result.answer,
                                   "on_topic": result.on_topic}])[-30:]
    return {"answer": result.answer, "on_topic": result.on_topic}


# =============================================================================
# Страница и статика
# =============================================================================
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
