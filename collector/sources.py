"""Parsers of the sources (pure functions of the text they got) and the code that fetches them.

A day is a string of 48 characters, one per half hour from 00:00: "0" power on, "1" off, "2" may be off.
A parser gives {queue: {"2026-11-22": "0011..."}}; a queue or a day that the source does not publish is absent.
"""
import gzip
import html
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import regions

KYIV = ZoneInfo("Europe/Kyiv")
SLOTS = 48
USER_AGENT = "Wattlo-Collector/1.0 (+https://github.com/termit-uanic/wattlo-data)"
# a volunteers' file older than this is not trusted (their script may have stopped)
MAX_FILE_AGE = timedelta(hours=48)


class SourceError(Exception):
    """The source did not give a usable answer (the text is for the log and for the report)."""


def today_kyiv(now: datetime = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KYIV).date()


# ---------------------------------------------------------------- bezsvitla.com.ua

_DATE_RE = re.compile(r'data-schedule-date="(\d{4}-\d\d-\d\d)"')
_TODAY_RE = re.compile(r'data-schedule-intervals="([^"]*)"')
_TOMORROW_RE = re.compile(r'data-schedule-tomorrow="([^"]*)"')
_ITEM_RE = re.compile(
    r'\{[^{}]*?"from"\s*:\s*"(\d\d):(\d\d)"[^{}]*?"to"\s*:\s*"(\d\d):(\d\d)"[^{}]*?"state"\s*:\s*"([A-Za-z_]+)"[^{}]*?\}')
_HEADINGS = ("Черга", "Група")  # most regions say "Черга 1.1", Chernivtsi region "Група 1"


def _bz_card(page: str, queue: str):
    """The part of the page with the card of the queue that holds the schedule, or None."""
    for word in _HEADINGS:
        marker = f"<strong>{word} {queue}</strong>"
        i = page.find(marker)
        while i >= 0:
            start = i + len(marker)
            ends = [e for e in (page.find(f"<strong>{w} ", start) for w in _HEADINGS) if e >= 0]
            seg = page[i:min(ends) if ends else len(page)]
            if "data-schedule-intervals" in seg:
                return seg
            i = page.find(marker, start)
    return None


def _bz_intervals(text: str):
    flags = ["0"] * SLOTS
    seen = [False] * SLOTS
    for m in _ITEM_RE.finditer(html.unescape(text)):
        fh, fm, th, tm, state = m.groups()
        a, b = int(fh) * 2 + int(fm) // 30, min(SLOTS, int(th) * 2 + int(tm) // 30)
        for s in range(a, b):
            flags[s] = "0" if state.upper() == "ON" else "1"
            seen[s] = True
    return "".join(flags) if all(seen) else None


def parse_bezsvitla(page: str, queues, today: date):
    out = {}
    for q in queues:
        card = _bz_card(page, q)
        if card is None:
            continue
        m = _DATE_RE.search(card)
        day = date.fromisoformat(m.group(1)) if m else today
        days = {}
        m = _TODAY_RE.search(card)
        if m and (s := _bz_intervals(m.group(1))):
            days[day.isoformat()] = s
        m = _TOMORROW_RE.search(card)
        if m and (s := _bz_intervals(m.group(1))):
            days[(day + timedelta(days=1)).isoformat()] = s
        if days:
            out[q] = days
    return out


# ---------------------------------------------------------------- YASNO

def parse_yasno(text: str, queues):
    data = json.loads(text)
    out = {}
    for q in queues:
        group = data.get(q)
        if not isinstance(group, dict):
            continue
        days = {}
        for key in ("today", "tomorrow"):
            d = group.get(key)
            if not isinstance(d, dict) or "date" not in d:
                continue
            status = d.get("status")
            if status == "NoOutages":
                states = "0" * SLOTS
            elif status == "ScheduleApplies" and d.get("slots"):
                flags = ["0"] * SLOTS
                for slot in d["slots"]:
                    state = {"NotPlanned": "0", "Definite": "1"}.get(slot.get("type"), "2")
                    for k in range(slot["start"] // 30, min(SLOTS, (slot["end"] + 29) // 30)):
                        flags[k] = state
                states = "".join(flags)
            else:
                continue  # WaitingForSchedule, EmergencyShutdowns: no schedule to show
            days[d["date"][:10]] = states
        if days:
            out[q] = days
    return out


# ---------------------------------------------------------------- the volunteers' files

# Checked against poe.pl.ua (the official schedule of Poltava) on all 12 queues: "msecond" is off in the first half of
# the hour and "may be off" in the second; "mfirst" is "may be off" in the first half and on in the second.
_HOUR = {"yes": "00", "no": "11", "maybe": "22", "first": "10", "second": "01", "mfirst": "20", "msecond": "12"}


def parse_mirror(text: str, queues, now: datetime = None):
    """{"lastUpdated": ..., "fact": {"data": {"<unix seconds of the start of the day>": {"GPV1.1": {"1": "yes", ...}}}}}.
    Key "h" is the hour that ends at h:00. A file without a day of today, or older than MAX_FILE_AGE, is refused."""
    now = now or datetime.now(timezone.utc)
    root = json.loads(text)
    updated = root.get("lastUpdated")
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            updated = None
    elif isinstance(updated, (int, float)):
        updated = datetime.fromtimestamp(updated, timezone.utc)
    else:
        updated = None
    if updated is not None and now - updated > MAX_FILE_AGE:
        raise SourceError(f"file not updated since {updated.isoformat()}")
    data = (root.get("fact") or {}).get("data") or {}
    out = {}
    for key, groups in data.items():
        try:
            day = datetime.fromtimestamp(int(key), timezone.utc).astimezone(KYIV).date().isoformat()
        except ValueError:
            continue
        for q in queues:
            hours = groups.get(f"GPV{q}")
            if not isinstance(hours, dict):
                continue
            out.setdefault(q, {})[day] = "".join(_HOUR.get(hours.get(str(h), ""), "00") for h in range(1, 25))
    if out and today_kyiv(now).isoformat() not in {d for days in out.values() for d in days}:
        raise SourceError("the file has no day of today")
    return out


# ---------------------------------------------------------------- fetching

def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
    except Exception as e:  # network errors, HTTP errors, timeouts
        raise SourceError(f"{type(e).__name__}: {e}") from e
    text = body.decode("utf-8", "replace")
    if "Just a moment" in text[:5000]:
        raise SourceError("the site asks for a browser check")
    return text


def fetch(source: str, region: regions.Region, getter=http_get, now: datetime = None):
    """{queue: {day: states}} of the region from the source; raises SourceError."""
    now = now or datetime.now(timezone.utc)
    if source == "bezsvitla":
        text = getter(f"https://bezsvitla.com.ua/{region.slug}")
        return parse_bezsvitla(text, region.queues, today_kyiv(now))
    if source == "yasno":
        rid, did = region.yasno
        text = getter(f"https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{rid}/dsos/{did}/planned-outages")
        return parse_yasno(text, region.queues)
    if source in regions.RAW_BASE:
        return parse_mirror(getter(regions.RAW_BASE[source] + region.data_file), region.queues, now)
    raise SourceError(f"unknown source {source}")
