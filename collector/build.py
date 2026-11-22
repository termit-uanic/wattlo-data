"""Collects every region from its sources and writes the files of format v1 (see README.md)."""
import json
import os
import sys
from datetime import datetime, timezone

from . import regions, sources

ATTRIBUTION = ("Schedules are collected from public sources (listed in 'sources'); the operators publish the official "
               "ones. Wattlo is not an official service.")
# a source is usable if it has today for at least this part of the region's queues
MIN_COVERAGE = 0.8


def covers_today(result, region, today: str) -> bool:
    have = sum(1 for q in region.queues if today in result.get(q, {}))
    return have >= MIN_COVERAGE * len(region.queues)


def same_power(a: str, b: str) -> bool:
    """Do two days say the same? Slots that either of them marks "may be off" ("2") are not compared: one source
    shows the switching half hour, another does not show it at all."""
    return all(x == y for x, y in zip(a, b) if x != "2" and y != "2")


def agreement(primary, other, today: str):
    """The part of the queues that have the same day today in both sources (None if nothing to compare)."""
    both = [q for q in primary if q in other and today in primary[q] and today in other[q]]
    if not both:
        return None
    return round(sum(same_power(primary[q][today], other[q][today]) for q in both) / len(both), 3)


def collect_region(region, fetcher=sources.fetch, now: datetime = None):
    """-> (the result of the first usable source or None, the report on every source tried)."""
    now = now or datetime.now(timezone.utc)
    today = sources.today_kyiv(now).isoformat()
    report, results = [], {}
    for source in region.sources:
        name, url = regions.SOURCE_INFO[source]
        entry = {"id": source, "name": name, "url": url}
        try:
            result = fetcher(source, region, now=now)
            if not covers_today(result, region, today):
                raise sources.SourceError("no schedule of today for most queues")
            results[source] = result
            entry["ok"] = True
        except (sources.SourceError, ValueError, KeyError, TypeError) as e:
            entry["ok"] = False
            entry["error"] = str(e)[:200]
        report.append(entry)
    primary = next((s for s in region.sources if s in results), None)
    for entry in report:
        if entry["id"] != primary and entry["id"] in results:
            entry["agreement"] = agreement(results[primary], results[entry["id"]], today)
    return primary, (results.get(primary) if primary else None), report


def region_file(region, primary, result, report, previous, now):
    """The document of a region. "updatedAt" is when the schedule last changed (it stays as it was while it does not)."""
    days = {}
    for q in region.queues:
        for day, states in result.get(q, {}).items():
            days.setdefault(day, {})[q] = states
    days = dict(sorted(days.items()))
    changed = previous is None or previous.get("days") != days
    return {
        "version": 1,
        "region": region.slug,
        "name": {"uk": region.name_uk, "en": region.name_en},
        "queues": region.queues,
        "source": primary,
        "sources": report,
        "days": days,
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ") if changed else previous.get("updatedAt"),
        "attribution": ATTRIBUTION,
    }


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def dump(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def run(out_dir: str, site_dir: str = None, fetcher=sources.fetch, now: datetime = None) -> int:
    """Writes out_dir/regions/<slug>.json and out_dir/index.json (no clock in them: they change only with the
    schedules, so they can be committed). With site_dir, the same files with "checkedAt" go there (to be published).
    Returns the number of regions that are not served for today."""
    now = now or datetime.now(timezone.utc)
    today = sources.today_kyiv(now).isoformat()
    index, failing = [], 0
    for region in regions.REGIONS:
        path = os.path.join(out_dir, "regions", region.slug + ".json")
        previous = load_json(path)
        primary, result, report = collect_region(region, fetcher, now)
        if primary is None:
            # nothing usable: keep what we have, but say so
            doc = previous or {"version": 1, "region": region.slug, "queues": region.queues, "days": {}}
            doc["sources"] = report
            doc["source"] = None
            served = bool(previous) and today in (previous.get("days") or {})
            failing += 0 if served else 1
        else:
            doc = region_file(region, primary, result, report, previous, now)
        dump(path, doc)
        index.append({"region": region.slug, "name": {"uk": region.name_uk, "en": region.name_en},
                      "source": doc.get("source"), "updatedAt": doc.get("updatedAt"),
                      "days": sorted((doc.get("days") or {}).keys())})
        print(f"{region.slug:26} {doc.get('source') or 'NONE':10} " +
              ", ".join(f"{e['id']}={'ok' if e['ok'] else 'FAIL'}" + (f"({e['agreement']})" if e.get('agreement') is not None else "")
                        for e in report), file=sys.stderr)
    dump(os.path.join(out_dir, "index.json"), {"version": 1, "regions": index})
    if site_dir:
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        for name in ["index.json"] + [os.path.join("regions", r.slug + ".json") for r in regions.REGIONS]:
            doc = load_json(os.path.join(out_dir, name))
            doc["checkedAt"] = stamp
            dump(os.path.join(site_dir, name), doc)
    return failing
