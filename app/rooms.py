"""Комнаты и ученики. Всё хранится в памяти процесса и удаляется по TTL.

На бесплатном Render диск и память сбрасываются при каждом перезапуске, поэтому комната умеет
«воскресать»: учитель и ученики хранят у себя в браузере токен и снимок состояния и при 404
восстанавливают комнату автоматически (см. /api/teacher/restore и /api/join).
"""
from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass, field

from . import simulator
from .config import settings
from .security import clean_name

ONLINE_SECONDS = 45


class StoreFull(Exception):
    """Слишком много активных комнат."""


class RoomFull(Exception):
    """В комнате нет мест."""


@dataclass
class Student:
    id: str
    name: str
    joined_at: float
    last_seen: float
    state: dict
    discovered: set = field(default_factory=set)
    recent_events: deque = field(default_factory=lambda: deque(maxlen=6))
    history: list = field(default_factory=list)  # [(role, text)] — только то, что уходит в модель
    log: list = field(default_factory=list)      # журнал вопросов к ИИ для учителя
    actions: int = 0
    questions: int = 0
    off_topic: int = 0


@dataclass
class Room:
    code: str
    subject: str
    title: str
    items: list
    created_at: float
    last_activity: float
    students: dict = field(default_factory=dict)


class RoomStore:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.closed: dict[str, float] = {}

    # --- комнаты ---------------------------------------------------------
    def _new_code(self) -> str:
        for _ in range(100):
            code = str(100000 + secrets.randbelow(900000))
            if code not in self.rooms and code not in self.closed:
                return code
        raise StoreFull()

    def create(self, subject: str, title: str, items: list, code: str | None = None) -> Room:
        self.purge()
        if len(self.rooms) >= settings.max_rooms:
            raise StoreFull()
        now = time.time()
        room = Room(code or self._new_code(), subject, title, list(items), now, now)
        self.rooms[room.code] = room
        return room

    def get(self, code: str) -> Room | None:
        return self.rooms.get(code)

    def close(self, code: str) -> None:
        self.rooms.pop(code, None)
        self.closed[code] = time.time()

    def was_closed(self, code: str) -> bool:
        return code in self.closed

    def purge(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        dead = [c for c, r in self.rooms.items() if now - r.last_activity > settings.room_ttl_seconds]
        for code in dead:
            del self.rooms[code]
        for code in [c for c, ts in self.closed.items() if now - ts > settings.room_ttl_seconds]:
            del self.closed[code]
        return len(dead)

    # --- ученики ---------------------------------------------------------
    def add_student(self, room: Room, name: str, sid: str | None = None) -> Student:
        if len(room.students) >= settings.max_students_per_room:
            raise RoomFull()
        taken = {s.name for s in room.students.values()}
        unique, n = name, 2
        while unique in taken:
            unique = f"{name} ({n})"
            n += 1
        now = time.time()
        student = Student(
            id=sid or secrets.token_hex(6), name=unique, joined_at=now, last_seen=now,
            state=simulator.empty_state(room.subject),
        )
        room.students[student.id] = student
        room.last_activity = now
        return student


def touch(room: Room, student: Student | None = None) -> None:
    now = time.time()
    room.last_activity = now
    if student:
        student.last_seen = now


def progress(room: Room, student: Student) -> tuple[list[str], int]:
    """(найденные наблюдения в порядке каталога, сколько всего можно найти)."""
    available = simulator.available_events(room.subject, room.items)
    return [e for e in available if e in student.discovered], len(available)


def teacher_summary(room: Room) -> list[dict]:
    now = time.time()
    available = simulator.available_events(room.subject, room.items)
    rows = []
    for s in sorted(room.students.values(), key=lambda x: x.joined_at):
        found = [e for e in available if e in s.discovered]
        rows.append({
            "id": s.id,
            "name": s.name,
            "online": now - s.last_seen < ONLINE_SECONDS,
            "found": len(found),
            "found_ids": found,
            "total": len(available),
            "actions": s.actions,
            "questions": s.questions,
            "off_topic": s.off_topic,
        })
    return rows
