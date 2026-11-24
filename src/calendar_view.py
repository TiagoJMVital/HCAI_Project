"""Read-only weekly calendar view data and deliberately narrow request parsing.

This module is presentation-only: it does not edit scenarios, proposals or labels.
The v2 UI passes local, timezone-naive display copies of timezone-aware inputs.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

HOUR_PX = 60
DAY_PX = 24 * HOUR_PX
DAYS_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
WEEKDAYS_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

CATEGORY_STYLE = {
    "class": ("academic", "Académico / aula"),
    "academic": ("academic", "Académico"),
    "academic_deadline": ("academic", "Prazo académico"),
    "gym": ("gym", "Ginásio / atividade flexível"),
    "health": ("health", "Saúde"),
    "study": ("study", "Estudo"),
    "supervisor_meeting": ("meeting", "Reunião"),
    "meeting": ("meeting", "Reunião"),
    "social": ("social", "Social"),
    "travel": ("travel", "Viagem"),
}


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    source: str

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError("intervalo sem duração positiva")


@dataclass(frozen=True)
class ViewEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    category: str
    importance: int
    fixed: bool
    change_status: str = "unchanged"  # added, moved, removed, previous_position


@dataclass(frozen=True)
class Segment:
    event: ViewEvent
    day: date
    start_minute: int
    end_minute: int
    top_px: float
    height_px: float
    lane: int
    lane_count: int
    in_requested_interval: bool
    milestone: bool


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_after(week_start: date, offset: int) -> date:
    return week_start + timedelta(days=7 * offset)


def _parse_iso_datetime(day: str, clock: str) -> datetime | None:
    try:
        return datetime.fromisoformat(f"{day}T{clock}")
    except ValueError:
        return None


def _unique_weekday(request: str) -> int | None:
    mentioned = {index for index, name in enumerate(WEEKDAYS_EN)
                 if re.search(rf"\b{name}\b", request, re.IGNORECASE)}
    return next(iter(mentioned)) if len(mentioned) == 1 else None


def _anchored_weekday_date(weekday: int, now: datetime,
                           calendar: list[dict]) -> date | None:
    """Use a unique calendar date in the next seven days, never the host date."""
    candidate_dates: set[date] = set()
    for event in calendar:
        try:
            start = datetime.fromisoformat(event["start"])
            end = datetime.fromisoformat(event["end"])
        except (KeyError, TypeError, ValueError):
            continue
        cursor = start.date()
        while cursor <= end.date():
            if cursor.weekday() == weekday and 0 <= (cursor - now.date()).days < 7:
                candidate_dates.add(cursor)
            cursor += timedelta(days=1)
    return next(iter(candidate_dates)) if len(candidate_dates) == 1 else None


def identify_requested_interval(packet: dict) -> Interval | None:
    """Recognize only a single, explicit date/time interval and safe weekday anchor.

    Supported: 'from YYYY-MM-DD HH:MM to YYYY-MM-DD HH:MM'; or one named
    weekday plus a clock range HH:MM-HH:MM; or 'between H and H' with an
    explicit 'morning' qualifier. A weekday is accepted only when exactly one
    corresponding calendar date occurs in the seven days after scenario.now.
    Vague 'morning', deadlines, single appointments and multiple weekdays are
    intentionally not interpreted as target windows.
    """
    request = packet["user_request"]
    if not re.search(r"\b(clear|free|reserve|schedule|book|add|block)\b", request, re.I):
        return None
    if re.search(r"\b(?:do not|don't|never|avoid|without)\s+(?:\w+\s+){0,2}"
                 r"(?:clear|free|reserve|schedule|book|add|block)\b", request, re.I):
        return None
    now = datetime.fromisoformat(packet["now"])

    iso_pattern = (r"\bfrom\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})\s+to\s+"
                   r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})\b")
    iso = list(re.finditer(iso_pattern, request, re.I))
    if iso:
        if len(iso) != 1:
            return None
        start = _parse_iso_datetime(iso[0][1], iso[0][2])
        end = _parse_iso_datetime(iso[0][3], iso[0][4])
        return Interval(start, end, "explicit ISO date/time range") if start and end and end > start else None

    weekday = _unique_weekday(request)
    if weekday is None or re.search(r"\bnext\s+" + WEEKDAYS_EN[weekday] + r"\b", request, re.I):
        return None  # 'next Thursday' varies by locale; no implicit interpretation.
    day = _anchored_weekday_date(weekday, now, packet["calendar"])
    if day is None:
        return None

    clock_range = list(re.finditer(r"\b([01]\d|2[0-3]):([0-5]\d)\s*[-–]\s*"
                                   r"([01]\d|2[0-3]):([0-5]\d)\b", request))
    if len(clock_range) == 1:
        m = clock_range[0]
        start = datetime.combine(day, time(int(m[1]), int(m[2])))
        end = datetime.combine(day, time(int(m[3]), int(m[4])))
        return Interval(start, end, "weekday + explicit 24-hour range") if end > start and start >= now else None

    bare = list(re.finditer(r"\bbetween\s+(\d{1,2})\s+and\s+(\d{1,2})\b", request, re.I))
    if len(bare) == 1 and re.search(r"\bmorning\b", request, re.I):
        start_hour, end_hour = int(bare[0][1]), int(bare[0][2])
        if 5 <= start_hour <= 11 and 6 <= end_hour <= 12 and start_hour < end_hour:
            start = datetime.combine(day, time(start_hour))
            end = datetime.combine(day, time(end_hour))
            return Interval(start, end, "weekday + explicit morning hours") if start >= now else None
    return None


def initial_week(packet: dict, interval: Interval | None) -> date:
    if interval is not None:
        return monday_of(interval.start.date())
    now = datetime.fromisoformat(packet["now"])
    starts = []
    for event in packet["calendar"]:
        try:
            start = datetime.fromisoformat(event["start"])
            if start >= now:
                starts.append(start)
        except (KeyError, TypeError, ValueError):
            continue
    return monday_of(min(starts).date() if starts else now.date())


def view_events(calendar: list[dict], *, status_by_id: dict[str, str] | None = None) -> list[ViewEvent]:
    status_by_id = status_by_id or {}
    result = []
    for raw in calendar:
        result.append(ViewEvent(raw["id"], raw["title"],
                                datetime.fromisoformat(raw["start"]),
                                datetime.fromisoformat(raw["end"]),
                                raw["category"], raw["importance"], raw["fixed"],
                                status_by_id.get(raw["id"], "unchanged")))
    return result


def overlaps(event: ViewEvent, interval: Interval) -> bool:
    return event.start < interval.end and interval.start < event.end


def overlap_summary(events: Iterable[ViewEvent], interval: Interval | None) -> dict | None:
    if interval is None:
        return None
    hits = [event for event in events if event.change_status not in ("removed", "previous_position")
            and overlaps(event, interval)]
    return {"total": len(hits), "fixed": sum(event.fixed for event in hits),
            "flexible": sum(not event.fixed for event in hits),
            "events": hits}


def _daily_segments(events: list[ViewEvent], day: date,
                    interval: Interval | None) -> list[Segment]:
    day_start = datetime.combine(day, time.min)
    next_day = day_start + timedelta(days=1)
    rows = []
    for event in events:
        milestone = event.start == event.end
        if milestone:
            if not day_start <= event.start < next_day:
                continue
            first = event.start
            last = min(event.start + timedelta(minutes=15), next_day)
        else:
            if event.end <= day_start or event.start >= next_day:
                continue
            first, last = max(event.start, day_start), min(event.end, next_day)
        start_min = int((first - day_start).total_seconds() // 60)
        end_min = int((last - day_start).total_seconds() // 60)
        rows.append((event, start_min, end_min, milestone))
    rows.sort(key=lambda x: (x[1], x[2], x[0].id))

    # Assign independent lanes to temporally overlapping blocks.
    clusters: list[list[tuple[ViewEvent, int, int, bool, int, int]]] = []
    cluster: list[tuple[ViewEvent, int, int, bool, int, int]] = []
    active: list[tuple[int, int]] = []
    for event, start_min, end_min, milestone in rows:
        active = [(end, lane) for end, lane in active if end > start_min]
        if not active and cluster:
            clusters.append(cluster)
            cluster = []
        occupied = {lane for _, lane in active}
        lane = next(i for i in range(len(occupied) + 1) if i not in occupied)
        active.append((end_min, lane))
        cluster.append((event, start_min, end_min, milestone, lane, 0))
    if cluster:
        clusters.append(cluster)

    out = []
    for group in clusters:
        count = max(row[4] for row in group) + 1
        for event, start_min, end_min, milestone, lane, _ in group:
            top = start_min / 60 * HOUR_PX
            out.append(Segment(event, day, start_min, end_min,
                               min(top, DAY_PX - 12) if milestone else top,
                               max((end_min - start_min) / 60 * HOUR_PX, 8),
                               lane, count,
                               bool(interval and overlaps(event, interval)),
                               milestone))
    return out


def week_segments(events: list[ViewEvent], week_start: date,
                  interval: Interval | None = None) -> list[Segment]:
    return [seg for index in range(7)
            for seg in _daily_segments(events, week_start + timedelta(days=index), interval)]


def interval_segments(interval: Interval | None, week_start: date) -> list[dict]:
    if interval is None:
        return []
    out = []
    for index in range(7):
        day = week_start + timedelta(days=index)
        begin = datetime.combine(day, time.min)
        end = begin + timedelta(days=1)
        first, last = max(begin, interval.start), min(end, interval.end)
        if first < last:
            out.append({"day": day, "top_px": (first - begin).total_seconds() / 3600 * HOUR_PX,
                        "height_px": (last - first).total_seconds() / 3600 * HOUR_PX})
    return out


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def render_week_html(events: list[ViewEvent], week_start: date,
                     interval: Interval | None, *, comparison_palette: bool = False) -> str:
    """Escaped, read-only HTML/CSS; no scripts or event mutation controls."""
    segments = week_segments(events, week_start, interval)
    highlights = interval_segments(interval, week_start)
    by_day: dict[date, list[Segment]] = {week_start + timedelta(days=i): [] for i in range(7)}
    for segment in segments:
        by_day[segment.day].append(segment)
    highlight_by_day = {item["day"]: item for item in highlights}
    head = "".join(f"<div class='hcai-day-heading'>{DAYS_PT[i]}<br><strong>{(week_start + timedelta(days=i)).strftime('%d/%m')}</strong></div>"
                   for i in range(7))
    hours = "".join(f"<span style='top:{hour * HOUR_PX}px'>{hour:02d}:00</span>" for hour in range(24))
    cells = []
    for index in range(7):
        day = week_start + timedelta(days=index)
        parts = []
        if day in highlight_by_day:
            item = highlight_by_day[day]
            parts.append(f"<div class='hcai-target' style='top:{item['top_px']:.1f}px;height:{item['height_px']:.1f}px' "
                         "aria-label='Intervalo solicitado pelo utilizador'></div>")
        for segment in by_day[day]:
            event = segment.event
            group = CATEGORY_STYLE.get(event.category, ("other", "Outro"))[0]
            status = event.change_status
            label = ("Fixo" if event.fixed else "Flexível")
            if status == "added":
                label += " · Adicionado"
            elif status == "moved":
                label += " · Movido"
            elif status == "preserved":
                label += " · Preservado"
            elif status == "removed":
                label += " · Removido (referência)"
            elif status == "previous_position":
                label += " · Posição anterior (referência)"
            if segment.milestone:
                label += " · Marco pontual"
            title = html.escape(event.title)
            full_times = f"{event.start:%d/%m %H:%M}–{event.end:%d/%m %H:%M}"
            duration_minutes = int((event.end - event.start).total_seconds() // 60)
            detail = html.escape(f"{event.title}; {full_times}; duração {duration_minutes} min; categoria {event.category}; "
                                 f"importância {event.importance}/5; {label}", quote=True)
            left = segment.lane / segment.lane_count * 100
            width = 100 / segment.lane_count
            classes = f"hcai-event hcai-{group} hcai-{status}"
            if segment.in_requested_interval and status not in ("removed", "previous_position"):
                classes += " hcai-overlap"
            card = (f"<div class='{classes}' tabindex='0' title='{detail}' aria-label='{detail}' "
                    f"style='top:{segment.top_px:.1f}px;height:{segment.height_px:.1f}px;"
                    f"left:{left:.3f}%;width:calc({width:.3f}% - 3px)'>"
                    f"<strong>{title}</strong><small>{_clock(segment.start_minute)}–"
                    f"{_clock(segment.end_minute) if not segment.milestone else _clock(segment.start_minute)}</small>"
                    f"<small>{html.escape(label)}</small></div>")
            parts.append(card)
        cells.append(f"<div class='hcai-day-track' role='group' aria-label='{DAYS_PT[index]} {day:%d/%m/%Y}'>"
                     + "".join(parts) + "</div>")
    return ("<style>"
            ".hcai-wrap{overflow:auto;max-height:760px;border:1px solid #cbd5e1;border-radius:10px;"
            "font-family:system-ui,sans-serif;background:#fff;color:#172033}"
            ".hcai-calendar{min-width:760px}"
            ".hcai-header{display:grid;grid-template-columns:58px repeat(7,minmax(100px,1fr));"
            "position:sticky;top:0;z-index:10;background:#f8fafc;border-bottom:1px solid #cbd5e1}"
            ".hcai-day-heading{text-align:center;padding:6px 2px;font-size:13px;border-left:1px solid #e2e8f0}"
            ".hcai-body{display:grid;grid-template-columns:58px repeat(7,minmax(100px,1fr))}"
            f".hcai-hours,.hcai-day-track{{height:{DAY_PX}px;position:relative;"
            f"background:repeating-linear-gradient(to bottom,#fff 0,#fff {HOUR_PX - 1}px,#e5e7eb {HOUR_PX - 1}px,#e5e7eb {HOUR_PX}px)}}"
            ".hcai-hours{border-right:1px solid #cbd5e1;color:#475569}"
            ".hcai-hours span{position:absolute;right:5px;transform:translateY(-7px);font-size:11px}"
            ".hcai-day-track{border-right:1px solid #e2e8f0}"
            ".hcai-target{position:absolute;left:0;right:0;background:rgba(245,158,11,.18);"
            "outline:2px dashed #9a5700;outline-offset:-2px;z-index:1;pointer-events:none}"
            ".hcai-event{position:absolute;z-index:2;box-sizing:border-box;border-radius:5px;padding:2px 4px;"
            "overflow:hidden;font-size:11px;line-height:1.25;border:1px solid #64748b;"
            "background:#e2e8f0;color:#172033}"
            ".hcai-event strong,.hcai-event small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
            ".hcai-event:hover,.hcai-event:focus{z-index:5;outline:2px solid #172033;overflow:visible}"
            ".hcai-academic{background:#fbd5c7;border-color:#b93f22}"
            ".hcai-gym{background:#cfe5ff;border-color:#2664b8}"
            ".hcai-health{background:#cef2dd;border-color:#198754}"
            ".hcai-study{background:#e4d7fa;border-color:#7654aa}"
            ".hcai-meeting{background:#c8ecee;border-color:#16818a}"
            ".hcai-social{background:#ffe6b5;border-color:#aa6a00}"
            ".hcai-travel{background:#dce3ec;border-color:#52647c}"
            ".hcai-overlap{outline:3px solid #8a3d00;outline-offset:-2px}"
            ".hcai-added{border-style:dashed;border-width:3px}"
            ".hcai-moved{border-width:3px}"
            ".hcai-removed,.hcai-previous_position{opacity:.55;border-style:dashed;background:#f1f5f9}"
            ".hcai-comparison .hcai-unchanged,.hcai-comparison .hcai-preserved{background:#e5e7eb;border-color:#64748b}"
            ".hcai-comparison .hcai-added{background:#bbf7d0;border-color:#15803d;color:#14532d}"
            ".hcai-comparison .hcai-moved{background:#bfdbfe;border-color:#1d4ed8;color:#1e3a8a}"
            ".hcai-comparison .hcai-removed,.hcai-comparison .hcai-previous_position{background:#fecaca;border-color:#b91c1c;color:#7f1d1d}"
            "</style>"
            f"<div class='hcai-wrap{' hcai-comparison' if comparison_palette else ''}'><div class='hcai-calendar'>"
            "<div class='hcai-header'><div></div>" + head + "</div>"
            "<div class='hcai-body'><div class='hcai-hours'>" + hours + "</div>"
            + "".join(cells) + "</div></div></div>")
