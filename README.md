# wattlo-data

The schedules of power outages in Ukraine for the [Wattlo](https://github.com/termit-uanic/wattlo) app (an Android phone
and Wear OS watch app), collected from public sources into one small JSON file per region.

* **What it is:** a collector (Python, no dependencies) that GitHub Actions runs every 7 minutes. It asks the sources of
  every region, picks the first usable one, compares it with the others, and writes `data/v1/regions/<region>.json`.
  The files are committed when a schedule changes, so the history of this repository is the history of the schedules.
* **What the app reads:** the same files with the time of the check, published to GitHub Pages
  (`https://wattlo.poltorak.family/v1/index.json`, `.../v1/regions/<region>.json`).
* **Not an official service.** The schedules come from the sources below and may differ from the actual outages;
  emergency outages are usually not in them at all.

## Format `v1`

`v1/index.json` lists the regions: `{"version": 1, "regions": [{"region", "name": {"uk", "en"}, "source", "updatedAt", "days"}]}`.

`v1/regions/<region>.json` (the name of the file is the page of the region on bezsvitla.com.ua):

```json
{
 "version": 1,
 "region": "lvivska-oblast",
 "name": {"uk": "Львівська область", "en": "Lviv region"},
 "queues": ["1.1", "1.2", "..."],
 "source": "bezsvitla",
 "sources": [{"id": "bezsvitla", "name": "bezsvitla.com.ua", "url": "https://bezsvitla.com.ua/", "ok": true},
             {"id": "oe_data", "name": "OE_OUTAGE_DATA (GitHub)", "url": "...", "ok": true, "agreement": 1.0}],
 "days": {"2026-11-22": {"1.1": "000000...", "1.2": "..."}, "2026-11-23": {"...": "..."}},
 "updatedAt": "2026-11-22T15:59:18Z",
 "checkedAt": "2026-11-22T16:05:02Z",
 "attribution": "..."
}
```

* `queues`: the queues (groups) of the region; Kyiv has 60 sub-queues (`1.1` … `60.1`), Ternopil region 14, Chernivtsi
  region 12 groups (`1` … `12`), the others 12 (`1.1` … `6.2`).
* `days`: a day (the date in Kyiv) holds the state of every queue as 48 characters, one per half hour from 00:00:
  `0` power on, `1` off, `2` may be off (the half hour of switching). Only the days the source has published are there
  (today, and tomorrow once it is published).
* `source`: the source the data is from (`null` when none works: the old file is kept); `sources`: every source that was
  tried, whether it answered, and `agreement`: the part of the queues whose schedule of today is the same as in the chosen
  source (the half hours marked `2` are not compared).
* `updatedAt`: when the schedule last changed. `checkedAt` (only in the published files): when the collector last looked,
  a file whose `checkedAt` is old means the collector has stopped.

## Sources

In the order they are tried (see `collector/regions.py`; the first one that has a schedule of today for most queues wins):

* [YASNO](https://yasno.ua/) (`app.yasno.ua`, the planned-outages JSON): Kyiv, Dnipropetrovsk region (operator DnEM).
* [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua): the JSON of DTEK (Kyiv, Kyiv region,
  Dnipropetrovsk region, Odesa region).
* [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA) and
  [vn-progr/gpv-voe-vinnytsia](https://github.com/vn-progr/gpv-voe-vinnytsia): the JSON of the regional power companies,
  collected by volunteers. They sometimes lag behind the sites by hours, so bezsvitla.com.ua goes before them.
* [bezsvitla.com.ua](https://bezsvitla.com.ua/): the page of every region (its terms allow using the materials with an
  active link to it, which is what `sources` is for).
* poe.pl.ua, the official schedule of Poltava region, does not answer to requests from outside Ukraine (the GitHub runners
  are in the USA), so it is not used here; the Wattlo app asks it directly.

The hours of the volunteers' files (`yes`, `no`, `first`, `second`, `maybe`, `mfirst`, `msecond`) were checked against
poe.pl.ua on all queues of Poltava region: `msecond` is off in the first half of the hour and "may be off" in the second,
`mfirst` the other way round.

## Run and test

```bash
python -m collector data/v1 --site _site/v1     # exit code 1: a region has no schedule of today from any source
python -m unittest discover -s tests -t .
```

MIT, see [LICENSE](LICENSE).
