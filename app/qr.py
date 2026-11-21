"""QR-код делает сервер (библиотека segno, чистый Python) — без CDN и сторонних скриптов на странице."""
from __future__ import annotations

import io


def make_qr_svg(text: str) -> str:
    import segno  # импорт здесь: модуль не нужен тестам ядра

    qr = segno.make(text, error="m", micro=False)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8, border=2, dark="#10243e", light="#ffffff",
            xmldecl=False, svgns=True, nl=False)
    return buf.getvalue().decode("utf-8")
