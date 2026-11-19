"""Настройки Himolik.

Секреты читаются из переменных окружения или локального файла .env.
.env игнорируется Git и никогда не отдаётся фронтенду.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("himolik")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        # --- Gemini ---------------------------------------------------------
        self.gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "").strip()
        # Цепочка моделей: если у первой закончилась квота (429) или её отключили (404),
        # запрос уйдёт к следующей. У каждой модели в бесплатном тарифе своя квота.
        models = os.environ.get(
            "GEMINI_MODELS",
            "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash",
        )
        self.gemini_models: list[str] = [m.strip() for m in models.split(",") if m.strip()]
        # Необязательно: low / medium / high. Пусто = значение по умолчанию у модели.
        self.gemini_thinking_level: str = os.environ.get("GEMINI_THINKING_LEVEL", "").strip()
        # Не больше стольких запросов к Gemini в минуту со всего сервера (бесплатный тариф ≈ 10).
        self.gemini_rpm: int = _env_int("GEMINI_RPM_LIMIT", 9)
        self.gemini_timeout: int = _env_int("GEMINI_TIMEOUT_SECONDS", 20)

        # --- Подпись токенов ------------------------------------------------
        secret = os.environ.get("SECRET_KEY", "").strip()
        self.secret_from_env: bool = bool(secret)
        # Без SECRET_KEY токены перестанут работать после перезапуска сервера.
        self.secret_key: str = secret or secrets.token_urlsafe(32)

        # --- Адрес сайта (для QR) -------------------------------------------
        # На Render переменная RENDER_EXTERNAL_URL выставляется автоматически.
        base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or ""
        self.public_base_url: str = base.strip().rstrip("/")

        # --- Персонаж --------------------------------------------------------
        self.assistant_name: str = os.environ.get("ASSISTANT_NAME", "Химолик").strip() or "Химолик"

        # --- Лимиты ---------------------------------------------------------
        self.room_ttl_seconds: int = _env_int("ROOM_TTL_SECONDS", 6 * 3600)
        self.max_rooms: int = _env_int("MAX_ROOMS", 300)
        self.max_students_per_room: int = _env_int("MAX_STUDENTS_PER_ROOM", 60)
        self.chat_max_chars: int = _env_int("CHAT_MAX_CHARS", 400)
        self.chat_per_student_per_min: int = _env_int("CHAT_PER_STUDENT_PER_MIN", 6)
        self.chat_per_student_per_hour: int = _env_int("CHAT_PER_STUDENT_PER_HOUR", 80)
        self.chat_per_room_per_min: int = _env_int("CHAT_PER_ROOM_PER_MIN", 40)
        self.max_body_bytes: int = _env_int("MAX_BODY_BYTES", 20_000)

        self.debug: bool = _env_bool("DEBUG", False)

    def warn_about_problems(self) -> None:
        if not self.gemini_api_key:
            log.warning("GEMINI_API_KEY не задан: ИИ-лаборант будет недоступен.")
        if not self.secret_from_env:
            log.warning(
                "SECRET_KEY не задан: сгенерирован временный. После перезапуска сервера "
                "все токены учителей и учеников станут недействительными."
            )


settings = Settings()
