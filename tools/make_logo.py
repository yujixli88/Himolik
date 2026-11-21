"""Генератор логотипа Himolik (SVG). Запуск: python tools/make_logo.py
Стиль: тёмный контур, серо-голубой, крем и оранжевый — как у персонажа."""
import math

NAVY, BLUE, CREAM, ORANGE = "#1e2433", "#a9c2d0", "#f3ece0", "#d48a3c"
SW = 7  # толщина контура
CX, CY = 200, 230


def gear_points(n=10, r_in=108, r_out=130):
    pts = []
    for i in range(n):
        a0 = i * 360 / n - 90
        for da, r in ((-11, r_in), (-7, r_out), (7, r_out), (11, r_in), (18, r_in)):
            a = math.radians(a0 + da)
            pts.append((CX + r * math.cos(a), CY + r * math.sin(a)))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def tile(x, y, w, sym, num, rot=0, fill=CREAM, size=None):
    size = size or int(w * 0.5)
    return (f'<g transform="translate({x} {y}) rotate({rot})">'
            f'<rect x="{-w/2}" y="{-w/2}" width="{w}" height="{w}" rx="{w*0.14:.1f}" fill="{fill}" '
            f'stroke="{NAVY}" stroke-width="{SW*0.8:.1f}" stroke-linejoin="round"/>'
            f'<text x="{-w/2+w*0.12:.1f}" y="{-w/2+w*0.3:.1f}" font-size="{w*0.22:.1f}" font-weight="700" '
            f'fill="{NAVY}">{num}</text>'
            f'<text x="0" y="{w*0.22:.1f}" font-size="{size}" font-weight="800" text-anchor="middle" '
            f'fill="{NAVY}">{sym}</text></g>')


FONT = "font-family=\"'Trebuchet MS','Segoe UI',Verdana,Arial,sans-serif\""


def icon_body():
    return f"""
  <!-- антенны, как у персонажа -->
  <path d="M{CX} 100 Q{CX+8} 60 {CX+36} 22" fill="none" stroke="{NAVY}" stroke-width="{SW-1}" stroke-linecap="round"/>
  <path d="M{CX+36} 4 C{CX+48} 18 {CX+50} 28 {CX+36} 30 C{CX+22} 28 {CX+24} 18 {CX+36} 4 Z" fill="{ORANGE}" stroke="{NAVY}" stroke-width="{SW-2}" stroke-linejoin="round"/>
  <path d="M{CX-14} 100 Q{CX-26} 66 {CX-52} 38" fill="none" stroke="{NAVY}" stroke-width="{SW-1}" stroke-linecap="round"/>
  <circle cx="{CX-58}" cy="30" r="12" fill="{CREAM}" stroke="{NAVY}" stroke-width="{SW-2}"/>
  <!-- пузырьки -->
  <circle cx="{CX+96}" cy="62" r="9" fill="none" stroke="{NAVY}" stroke-width="4"/>
  <circle cx="{CX+122}" cy="34" r="5" fill="none" stroke="{NAVY}" stroke-width="3.5"/>
  <circle cx="{CX-104}" cy="70" r="6" fill="none" stroke="{NAVY}" stroke-width="3.5"/>
  <!-- шестерёнка -->
  <polygon points="{gear_points()}" fill="{BLUE}" stroke="{NAVY}" stroke-width="{SW}" stroke-linejoin="round"/>
  <circle cx="{CX}" cy="{CY}" r="80" fill="{CREAM}" stroke="{NAVY}" stroke-width="{SW}"/>
  <circle cx="{CX}" cy="{CY}" r="94" fill="none" stroke="{NAVY}" stroke-width="3" stroke-dasharray="2 12" stroke-linecap="round"/>
  <!-- клетки таблицы Менделеева -->
  {tile(CX, CY, 104, "Hi", "1", size=54)}
  {tile(CX-92, CY+92, 52, "H", "1", rot=-12, fill=ORANGE, size=28)}
  {tile(CX+94, CY+90, 52, "O", "8", rot=10, fill=BLUE, size=28)}
"""


def svg(icon_only):
    h = 420 if icon_only else 520
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 {h}" role="img" aria-label="Himolik" {FONT}>',
             "<title>Himolik</title>", icon_body()]
    if not icon_only:
        parts.append(f'<text x="200" y="455" font-size="68" font-weight="800" text-anchor="middle" fill="{NAVY}">'
                     f'<tspan fill="{ORANGE}">Hi</tspan>molik</text>')
        parts.append(f'<text x="200" y="495" font-size="22" font-weight="600" text-anchor="middle" '
                     f'fill="{NAVY}" letter-spacing="2">ВИРТУАЛЬНАЯ ЛАБОРАТОРИЯ</text>')
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    open("static/img/logo.svg", "w", encoding="utf-8").write(svg(False))
    open("static/img/logo-icon.svg", "w", encoding="utf-8").write(svg(True))
    print("OK")
