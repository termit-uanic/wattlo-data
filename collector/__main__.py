"""python -m collector OUT_DIR [--site SITE_DIR]: collect all regions; the exit code is 1 if a region is not served for today."""
import argparse
import json
import sys

from . import build

p = argparse.ArgumentParser(prog="collector")
p.add_argument("out_dir")
p.add_argument("--site", help="also write the files with 'checkedAt' here (what is published)")
p.add_argument("--changes", help="write {region: [changed queues]} here (for the push step)")
args = p.parse_args()
changes = {}
failing = build.run(args.out_dir, args.site, changes=changes)
if args.changes:
    with open(args.changes, "w", encoding="utf-8") as f:
        json.dump(changes, f)
if failing:
    print(f"{failing} region(s) are not served for today", file=sys.stderr)
sys.exit(1 if failing else 0)
