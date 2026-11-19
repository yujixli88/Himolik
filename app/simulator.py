"""Симулятор опытов. Чистые функции, без сети и без FastAPI.

Зачем он нужен: что происходит в колбе или в цепи, определяет НЕ нейросеть, а детерминированная
модель. ИИ-лаборант получает результат модели как факт и только объясняет его. Поэтому он не
может «выдумать» реакцию, а обработка ошибок ИИ сводится к простому правилу: модель важнее.

Упрощения (их видит и ИИ, и ученик):
  * одна «порция» реагента ≈ 5 мл раствора 0,1 М;
  * реакции считаются по ионам и по порядку приоритета, без кинетики и температуры.
"""
from __future__ import annotations

import copy
import math
from collections import Counter

from . import catalog

MAX_FLASK = 12
MAX_CIRCUIT = 10

# --- Химия -------------------------------------------------------------------
# ионы, которые вносит одна порция реагента
CHEM_IONS = {
    "hcl": {"H+": 1, "Cl-": 1},
    "h2so4": {"H+": 2, "SO4": 1},
    "naoh": {"Na+": 1, "OH-": 1},
    "na2co3": {"Na+": 2, "CO3": 1},
    "cuso4": {"Cu2+": 1, "SO4": 1},
    "nacl": {"Na+": 1, "Cl-": 1},
    "agno3": {"Ag+": 1, "NO3-": 1},
    "bacl2": {"Ba2+": 1, "Cl-": 2},
}
INDICATORS = {"phph", "mo"}
NO_VOLUME = INDICATORS | {"zn"}  # капли индикатора и твёрдый цинк объём не меняют

PRECIP_COLOR = {
    "ppt_agcl": "#f4f4f0", "ppt_baso4": "#f7f7f7", "ppt_baco3": "#f0f0ea",
    "ppt_cu_oh_2": "#3f74d6", "ppt_ag2o": "#6a4630", "ppt_cuco3": "#4fb39b",
    "ppt_ag2co3": "#efe6a8", "displ_cu": "#b4601f", "displ_ag": "#aab0b7",
}
BASE_LIQUID = "#d6eaf3"
ZINC_COLOR = "#7d8187"
EPS = 1e-9

# --- Физика ------------------------------------------------------------------
EMF_PER_BATTERY = 4.5
R_INTERNAL = 0.5
R_RESISTOR = 10.0
R_BULB = 12.5
I_BULB_NOMINAL = 0.28
R_AMMETER = 0.1


# =============================================================================
# Состояние и действия
# =============================================================================
def empty_state(subject: str) -> dict:
    return {"flask": []} if subject == "chemistry" else {"circuit": []}


def apply_action(subject: str, state: dict, action: str, item: str | None = None,
                 index: int | None = None, allowed=()) -> tuple[dict, str | None]:
    """Применяет действие ученика. Возвращает (новое_состояние, код_ошибки|None). Исходное не меняется."""
    st = copy.deepcopy(state)
    chem = subject == "chemistry"
    seq = st["flask"] if chem else st["circuit"]
    limit = MAX_FLASK if chem else MAX_CIRCUIT

    if action == "add":
        if not item or item not in allowed:
            return state, "item_not_allowed"
        if len(seq) >= limit:
            return state, "flask_full" if chem else "circuit_full"
        seq.append(item if chem else ({"id": item, "on": False} if item == "switch" else {"id": item}))
    elif action == "remove":
        if index is None or not (0 <= index < len(seq)):
            return state, "bad_index"
        seq.pop(index)
    elif action == "reset":
        seq.clear()
    elif action == "toggle" and not chem:
        if index is None or not (0 <= index < len(seq)) or seq[index]["id"] != "switch":
            return state, "bad_index"
        seq[index]["on"] = not seq[index].get("on", False)
    else:
        return state, "bad_action"
    return st, None


def sanitize_state(subject: str, raw, allowed) -> dict:
    """Приводит присланный клиентом снимок к безопасному виду (для восстановления после перезапуска)."""
    state = empty_state(subject)
    if not isinstance(raw, dict):
        return state
    if subject == "chemistry":
        for iid in (raw.get("flask") or [])[:MAX_FLASK]:
            if isinstance(iid, str) and iid in allowed:
                state["flask"].append(iid)
    else:
        for el in (raw.get("circuit") or [])[:MAX_CIRCUIT]:
            if isinstance(el, dict) and el.get("id") in allowed:
                entry = {"id": el["id"]}
                if el["id"] == "switch":
                    entry["on"] = bool(el.get("on"))
                state["circuit"].append(entry)
    return state


def replay(subject: str, raw, allowed) -> tuple[dict, set]:
    """Пошагово повторяет снимок состояния и собирает открытые наблюдения."""
    clean = sanitize_state(subject, raw, allowed)
    state, found = empty_state(subject), set()
    prev = evaluate(subject, state)
    seq = clean["flask"] if subject == "chemistry" else clean["circuit"]
    for el in seq:
        iid = el if subject == "chemistry" else el["id"]
        state, err = apply_action(subject, state, "add", iid, None, allowed)
        if err:
            continue
        if subject == "physics" and el.get("on"):
            state, _ = apply_action(subject, state, "toggle", None, len(state["circuit"]) - 1, allowed)
        cur = evaluate(subject, state)
        found |= set(new_events(subject, prev, cur))
        prev = cur
    return state, found


# =============================================================================
# Оценка состояния
# =============================================================================
def evaluate(subject: str, state: dict) -> dict:
    """Возвращает {"obs": set, "view": dict, "ph": float|None, "neutral": float}."""
    return _evaluate_chem(state) if subject == "chemistry" else _evaluate_phys(state)


def _mix(colors: list[str]) -> str:
    rgb = [[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in colors]
    avg = [round(sum(ch) / len(rgb)) for ch in zip(*rgb)]
    return "#{:02x}{:02x}{:02x}".format(*avg)


def _evaluate_chem(state: dict) -> dict:
    flask = list(state.get("flask", []))
    counts = Counter(flask)
    ion: Counter = Counter()
    for rid, n in counts.items():
        for k, v in CHEM_IONS.get(rid, {}).items():
            ion[k] += v * n
    volume = sum(n for rid, n in counts.items() if rid not in NO_VOLUME)
    vol = max(volume, 1)

    obs: set[str] = set()
    precip: Counter = Counter()
    gases: set[str] = set()

    def react(consume: dict) -> float:
        n = min(ion[k] / c for k, c in consume.items())
        if n > EPS:
            for k, c in consume.items():
                ion[k] -= c * n
            return n
        return 0.0

    # 1) нейтрализация
    neutral = react({"H+": 1, "OH-": 1})
    if neutral:
        obs.add("neutralization")
    # 2) карбонат + кислота: CO3 → HCO3 → CO2
    ion["HCO3"] += react({"CO3": 1, "H+": 1})
    if react({"HCO3": 1, "H+": 1}):
        gases.add("CO2")
        obs.add("gas_co2")
    # 3) осадки
    for pid, consume in (
        ("ppt_agcl", {"Ag+": 1, "Cl-": 1}),
        ("ppt_baso4", {"Ba2+": 1, "SO4": 1}),
        ("ppt_baco3", {"Ba2+": 1, "CO3": 1}),
        ("ppt_cu_oh_2", {"Cu2+": 1, "OH-": 2}),
        ("ppt_ag2o", {"Ag+": 2, "OH-": 2}),
        ("ppt_cuco3", {"Cu2+": 1, "CO3": 1}),
        ("ppt_ag2co3", {"Ag+": 2, "CO3": 1}),
    ):
        n = react(consume)
        if n:
            precip[pid] += n
            obs.add(pid)
    # 4) цинк
    zn_left = float(counts.get("zn", 0))
    for pid, key, need in (("displ_ag", "Ag+", 2), ("displ_cu", "Cu2+", 1)):
        n = min(zn_left, ion[key] / need)
        if n > EPS:
            ion[key] -= need * n
            zn_left -= n
            ion["Zn2+"] += n
            precip[pid] += n
            obs.add(pid)
    n = min(zn_left, ion["H+"] / 2)
    if n > EPS:
        ion["H+"] -= 2 * n
        zn_left -= n
        ion["Zn2+"] += n
        gases.add("H2")
        obs.add("gas_h2")
    n = min(zn_left, ion["OH-"] / 2)
    if n > EPS:
        ion["OH-"] -= 2 * n
        zn_left -= n
        gases.add("H2")
        obs.add("zn_alkali")

    # pH по оставшимся ионам (0,1 М · порции / объём)
    ph: float | None
    if not flask:
        ph = None
    elif ion["H+"] > EPS:
        ph = -math.log10(0.1 * ion["H+"] / vol)
    elif ion["OH-"] > EPS:
        ph = 14 + math.log10(0.1 * ion["OH-"] / vol)
    elif ion["CO3"] > EPS:
        ph = 11.5
    elif ion["HCO3"] > EPS:
        ph = 8.3
    elif ion["Cu2+"] > EPS:
        ph = 4.2
    elif ion["Zn2+"] > EPS:
        ph = 5.5
    else:
        ph = 7.0

    # цвет раствора: ионы меди + индикаторы
    colors: list[str] = []
    if ion["Cu2+"] > EPS:
        c = ion["Cu2+"] / vol
        colors.append("#2d7fe0" if c >= 0.3 else "#5aa1e6" if c >= 0.12 else "#9ccaf0")
    if ph is not None and "phph" in counts:
        if ph > 10:
            colors.append("#d6336c")
        elif ph > 8.2:
            colors.append("#f4a9c8")
        if ph > 8.2:
            obs.add("ind_phph_pink")
    if ph is not None and "mo" in counts:
        if ph < 3.1:
            colors.append("#d9361f")
            obs.add("ind_mo_red")
        elif ph < 4.4:
            colors.append("#f08a2c")
        else:
            colors.append("#f2d338")
            if ph > 7.5:
                obs.add("ind_mo_yellow")
    liquid = _mix(colors) if colors else BASE_LIQUID

    solids = [{"id": pid, "color": PRECIP_COLOR[pid], "amount": round(a, 2)} for pid, a in precip.items()]
    if zn_left > EPS:
        solids.append({"id": "zn", "color": ZINC_COLOR, "amount": round(zn_left, 2)})

    view = {
        "kind": "chemistry",
        "flask": flask,
        "volume": volume,
        "liquid": liquid,
        "solids": solids,
        "gas": sorted(gases),
        "heat": neutral > 0,
        "ph": None if ph is None else round(ph, 1),
        "cu_blue": ion["Cu2+"] > EPS,
    }
    return {"obs": obs, "view": view, "ph": ph, "neutral": neutral}


def _bulb_status(ratio: float, closed: bool) -> str:
    if not closed or ratio < 0.1:
        return "off"
    if ratio < 0.6:
        return "dim"
    if ratio <= 1.15:
        return "normal"
    if ratio <= 1.8:
        return "bright"
    return "burned"


def _evaluate_phys(state: dict) -> dict:
    circ = list(state.get("circuit", []))
    ids = [e["id"] for e in circ]
    nb, nres, nbulb = ids.count("battery"), ids.count("resistor"), ids.count("bulb")
    nam, nvol = ids.count("ammeter"), ids.count("voltmeter")
    switches = [e for e in circ if e["id"] == "switch"]

    emf = EMF_PER_BATTERY * nb
    r_loads = R_RESISTOR * nres + R_BULB * nbulb
    r_total = R_INTERNAL * nb + r_loads + R_AMMETER * nam
    switches_closed = all(s.get("on") for s in switches)
    # Вольтметр подключается параллельно и в контур тока не входит.
    loop_elements = nres + nbulb + nam + len(switches)
    closed = nb > 0 and loop_elements > 0 and switches_closed
    has_loads = (nres + nbulb) > 0
    current = emf / r_total if closed and r_total > 0 else 0.0
    short = closed and not has_loads

    ratio = current / I_BULB_NOMINAL if nbulb else 0.0
    burned = nbulb > 0 and closed and ratio > 1.8
    shown_current = 0.0 if burned else current
    u_loads = shown_current * r_loads

    elements = []
    for idx, e in enumerate(circ):
        el = {"idx": idx, "id": e["id"]}
        if e["id"] == "switch":
            el["on"] = bool(e.get("on"))
        elif e["id"] == "bulb":
            el["status"] = _bulb_status(ratio, closed)
            el["value"] = round(shown_current * R_BULB, 2)
        elif e["id"] == "resistor":
            el["value"] = round(shown_current * R_RESISTOR, 2)
        elif e["id"] == "ammeter":
            el["value"] = round(shown_current, 2)
        elif e["id"] == "voltmeter":
            el["value"] = round(u_loads, 2)
        elements.append(el)

    obs: set[str] = set()
    status = _bulb_status(ratio, closed) if nbulb else None
    if status in ("dim", "normal", "bright"):
        obs.add("lamp_on")
    if status == "dim":
        obs.add("lamp_dim")
    if status == "bright":
        obs.add("lamp_bright")
    if burned:
        obs.add("lamp_burned")
    if nam and shown_current > 0:
        obs.add("ammeter_reading")
    if nvol and shown_current > 0:
        obs.add("voltmeter_reading")
    if nb >= 2 and shown_current > 0:
        obs.add("batteries_series")
    if nres >= 2 and shown_current > 0:
        obs.add("resistors_series")
    if nb and has_loads and switches and not switches_closed:
        obs.add("switch_open")
    if short:
        obs.add("short_circuit")

    view = {
        "kind": "physics",
        "elements": elements,
        "emf": round(emf, 2),
        "r_total": round(r_total, 2),
        "current": round(shown_current, 2),
        "closed": closed,
        "short": short,
        "burned": burned,
    }
    return {"obs": obs, "view": view, "ph": None, "neutral": 0.0}


# =============================================================================
# События, прогресс, описание для ИИ
# =============================================================================
def new_events(subject: str, prev: dict, cur: dict) -> list[str]:
    """Какие наблюдения появились после последнего действия (в порядке каталога)."""
    fresh = set(cur["obs"]) - set(prev["obs"])
    if (subject == "chemistry" and cur["view"]["flask"] and prev["ph"] is not None
            and "phph" in cur["view"]["flask"]
            and prev["ph"] > 8.2 and cur["ph"] is not None and cur["ph"] <= 8.2
            and cur["neutral"] > prev["neutral"]):
        fresh.add("ind_discolor")
    return [eid for eid in catalog.EVENTS if eid in fresh]


def available_events(subject: str, items) -> list[str]:
    """Наблюдения, которые вообще можно открыть с набором, выбранным учителем."""
    have = set(items)
    return [
        eid for eid, ev in catalog.EVENTS.items()
        if ev["subject"] == subject and all(any(i in have for i in group) for group in ev["requires"])
    ]


def describe_ru(subject: str, ev: dict) -> str:
    """Описание текущего опыта для ИИ-лаборанта (по-русски, только факты симулятора)."""
    view = ev["view"]
    if subject == "chemistry":
        if not view["flask"]:
            return "Колба пуста."
        counts = Counter(view["flask"])
        parts = []
        for rid, n in counts.items():
            item = catalog.ITEMS[rid]
            parts.append(f"{n}× {item['formula'] or item['name']['ru']}")
        lines = [f"В колбе: {', '.join(parts)} (порция ≈ 5 мл раствора 0,1 М)."]
        if view["ph"] is not None:
            lines.append(f"Расчётный pH ≈ {view['ph']}.")
        if view["cu_blue"]:
            lines.append("Раствор голубой (ионы Cu²⁺).")
        for pid in ("ppt_agcl", "ppt_baso4", "ppt_baco3", "ppt_cu_oh_2", "ppt_ag2o",
                    "ppt_cuco3", "ppt_ag2co3", "displ_cu", "displ_ag"):
            if pid in ev["obs"]:
                lines.append(catalog.EVENTS[pid]["ru"])
        for eid in ("neutralization", "gas_co2", "gas_h2", "zn_alkali",
                    "ind_phph_pink", "ind_mo_red", "ind_mo_yellow"):
            if eid in ev["obs"]:
                lines.append(catalog.EVENTS[eid]["ru"])
        return " ".join(lines)
    # физика
    if not view["elements"]:
        return "Цепь пуста."
    names = []
    for el in view["elements"]:
        base = catalog.ITEMS[el["id"]]["name"]["ru"]
        if el["id"] == "switch":
            base += " (замкнут)" if el["on"] else " (разомкнут)"
        names.append(base)
    lines = [f"Цепь (последовательное соединение): {', '.join(names)}."]
    lines.append(f"ЭДС ≈ {view['emf']} В, общее сопротивление ≈ {view['r_total']} Ом, ток ≈ {view['current']} А.")
    if not view["closed"]:
        lines.append("Цепь не замкнута или нет источника тока: тока нет.")
    if view["short"]:
        lines.append("Короткое замыкание: нет потребителей.")
    if view["burned"]:
        lines.append("Лампочка перегорела из-за слишком большого тока.")
    for el in view["elements"]:
        if el["id"] == "bulb":
            lines.append(f"Лампочка: {el['status']}.")
    return " ".join(lines)
