"""Безопасность: подписанные токены, лимиты запросов, очистка пользовательского ввода."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass

from .config import settings

CODE_RE = re.compile(r"[0-9]{6}")  # только ASCII-цифры; \d пропустил бы и другие алфавиты
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>]")


def valid_code(code: str) -> bool:
    return bool(code) and CODE_RE.fullmatch(code) is not None


# --- Токены ------------------------------------------------------------------
@dataclass(frozen=True)
class Claims:
    role: str   # "t" — учитель, "s" — ученик
    code: str   # код комнаты
    sid: str    # id ученика ("-" у учителя)


def _signature(payload: str) -> str:
    return hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def sign_token(role: str, code: str, sid: str = "-") -> str:
    """Токен без хранения на сервере: после перезапуска он остаётся действительным (если задан SECRET_KEY)."""
    payload = f"{role}.{code}.{sid}"
    return f"{payload}.{_signature(payload)}"


def verify_token(token: str | None) -> Claims | None:
    if not token or len(token) > 200 or not token.isascii():
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        role, code, sid = payload.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _signature(payload)):
        return None
    if role not in ("t", "s") or not valid_code(code) or not sid:
        return None
    return Claims(role, code, sid)


# --- Лимиты запросов ---------------------------------------------------------
class RateLimiter:
    """Скользящее окно в памяти. Ключ — любая строка («chat:студент», «ip:1.2.3.4» …)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def count(self, key: str, window: float, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        q = self._hits.get(key)
        if not q:
            return 0
        while q and now - q[0] >= window:
            q.popleft()
        return len(q)

    def add(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._hits.setdefault(key, deque()).append(now)

    def hit(self, key: str, limit: int, window: float, now: float | None = None) -> tuple[bool, int]:
        """(разрешено, через сколько секунд повторить)."""
        now = time.monotonic() if now is None else now
        if self.count(key, window, now) >= limit:
            q = self._hits[key]
            return False, max(1, int(window - (now - q[0])) + 1)
        self.add(key, now)
        return True, 0

    def cleanup(self, max_window: float = 3600.0, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] >= max_window]:
            del self._hits[key]


# --- Очистка ввода -----------------------------------------------------------
def clean_name(raw: str | None) -> str | None:
    """Имя ученика: буквы любых алфавитов, цифры, пробел и - _ . ' ; до 24 символов."""
    s = unicodedata.normalize("NFKC", raw or "")
    s = "".join(ch for ch in s if ch.isalnum() or ch in " -_.'’")
    s = " ".join(s.split())[:24].strip()
    return s or None


def clean_title(raw: str | None) -> str | None:
    s = unicodedata.normalize("NFKC", raw or "")
    s = _CONTROL.sub(" ", s)
    s = " ".join(s.split())[:80].strip()
    return s or None
