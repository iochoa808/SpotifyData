"""Remove collected plays the API reported twice, judged against the export.

    python src/dedupe_plays.py --zip my_spotify_data.zip --dry-run
    python src/dedupe_plays.py --zip my_spotify_data.zip

The API sometimes returns one listen as two or more plays: the same track,
closer together than the track is long, all in a single response. Measured on
2026-11-20, 765 such pairs, which the GDPR export explains:

  - one listen in pieces: paused, handed to another device, or the app closed,
    then resumed; the API logged each piece;
  - a single short segment, likely jumping ahead in a track already playing;
  - nothing in the export at all (bursts like four plays in six seconds);
  - a real repeat: the track heard twice in a row, its timestamps squeezed
    together by the API's drift (see import_history.TOLERANCE_SECONDS).

For each chain of such rows, the export decides how many listens there were,
and that many rows are kept, the earliest first:

  - the segments add up to the track heard n times (REPEAT_COVERAGE for two,
    one more track length for each further time);
  - or a pause between segments longer than BIG_PAUSE_SECONDS starts a new
    listen, as the two halves of a song split across two sittings.

Removed rows are moved, whole, to data/removed_plays.csv with the row kept in
their place and the reason, so nothing is lost and every removal can be
audited or undone. The importer reads that file too: the export segments these
rows stood for stay claimed, so a later import cannot bring them back as
"new" plays.
"""
from pathlib import Path
import argparse
import csv
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_history as ih  # noqa: E402

DATA = ih.CURRENT
REMOVED = ih.REMOVED
REMOVED_HEADER = ih.PLAY_HEADER + ["kept_id", "reason"]

# Rows of one track closer together than this much under its length cannot be
# two full listens. The margin absorbs rounding of duration and timestamps.
OVERLAP_MARGIN_SECONDS = 5
# The listen rule itself lives in import_history.group_listens, so collected
# and imported plays are judged the same way.
REPEAT_COVERAGE = ih.REPEAT_COVERAGE
BIG_PAUSE_SECONDS = ih.BIG_PAUSE_SECONDS
# How far before the first row and after the last to look for segments.
SEGMENT_MARGIN_SECONDS = 60


def chains(rows, durations, margin=OVERLAP_MARGIN_SECONDS):
    """Runs of collected rows of one track, each closer to the last than its length.

    rows: recently_played dicts. Imported rows (no context) are left out: they
    are the export's own records, one per segment, and never doubled.
    Yields lists of rows, oldest first, two or more long.
    """
    by_track = {}
    for row in rows:
        if row["context_type"]:
            by_track.setdefault(row["track_id"], []).append(row)
    for track_id, plays in by_track.items():
        plays.sort(key=lambda r: int(r["id"]))
        limit = durations.get(track_id, 0) - margin
        run = [plays[0]]
        for row in plays[1:]:
            if int(row["id"]) - int(run[-1]["id"]) < limit:
                run.append(row)
                continue
            if len(run) > 1:
                yield run
            run = [row]
        if len(run) > 1:
            yield run


def listens(segments, duration, coverage=REPEAT_COVERAGE, big_pause=BIG_PAUSE_SECONDS):
    """How many listens a set of export segments adds up to, and why.

    segments: (end_ts, ms_played) for the track, in any order. The export's ts
    is when a segment stopped, so a segment started at ts - ms_played.
    """
    if not segments or duration <= 0:
        return 1, "not_in_export" if not segments else "one_listen"
    groups = ih.group_listens(segments, duration, coverage, big_pause)
    if len(groups) == 1:
        return 1, "one_listen_in_pieces" if len(segments) > 1 else "one_listen"
    pauses = [later[0][0] - later[0][1] // 1000 - earlier[-1][0]
              for earlier, later in zip(groups, groups[1:])]
    split_by_pause = all(p > big_pause for p in pauses)
    return len(groups), "separate_sittings" if split_by_pause else "repeat"


def plan(rows, durations, segments_of, removed=()):
    """The rows to remove, each with the row kept in its place and why.

    segments_of: callable(track_id, start, end) -> [(end_ts, ms_played)].
    removed: rows an earlier run already removed. Chains are rebuilt with them
    in place, so each is judged on the same evidence every time and a re-run
    removes nothing new; judged without them, a shortened chain would see
    fewer export segments and could reach a different count.
    """
    gone = {r["id"] for r in removed}
    removals, tally = [], {}
    for run in chains(list(rows) + list(removed), durations):
        track_id = run[0]["track_id"]
        duration = durations.get(track_id, 0)
        first, last = int(run[0]["id"]), int(run[-1]["id"])
        segments = segments_of(track_id, first - duration - SEGMENT_MARGIN_SECONDS,
                               last + SEGMENT_MARGIN_SECONDS)
        count, reason = listens(segments, duration)
        keep = run[:count]
        fresh = [row for row in run[count:] if row["id"] not in gone]
        tally[reason] = tally.get(reason, 0) + len(fresh)
        tally[f"kept_{reason}"] = tally.get(f"kept_{reason}", 0) + len(keep)
        for row in fresh:
            removals.append({**{k: row[k] for k in ih.PLAY_HEADER},
                             "kept_id": keep[-1]["id"], "reason": reason})
    return removals, tally


def read_segments(zip_path):
    """track_id -> sorted [(end_ts, ms_played)], private sessions excluded."""
    segments = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if "Streaming_History_Audio" not in name or not name.endswith(".json"):
                continue
            with archive.open(name) as handle:
                for row in json.load(handle):
                    uri = row.get("spotify_track_uri")
                    if not uri or row.get("incognito_mode"):
                        continue
                    segments.setdefault(uri.rsplit(":", 1)[-1], []).append(
                        (ih.parse_ts(row["ts"]), row.get("ms_played") or 0))
    for values in segments.values():
        values.sort()
    return segments


def record_removed(rows, path=None):
    path = path or DATA / REMOVED
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REMOVED_HEADER, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", default="my_spotify_data.zip")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with open(DATA / "songs.csv", newline="", encoding="utf-8") as handle:
        durations = {r["id"]: int(r["duration_ms"] or 0) // 1000
                     for r in csv.DictReader(handle)}
    segments = read_segments(args.zip)

    def segments_of(track_id, start, end):
        return [s for s in segments.get(track_id, ()) if start <= s[0] <= end]

    rows = ih.read_current()
    removals, tally = plan(rows, durations, segments_of, ih.read_removed())
    print(f"Collected plays: {sum(1 for r in rows if r['context_type']):,}")
    width = max(map(len, tally), default=0) + 2
    for key in sorted(tally, key=lambda k: (k.startswith("kept_"), k)):
        print(f"  {'kept' if key.startswith('kept_') else 'remove'} {key.removeprefix('kept_'):<{width}}{tally[key]:>6,}")
    print(f"\nTo remove: {len(removals):,} plays")
    if args.dry_run or not removals:
        print("Dry run; nothing written." if args.dry_run else "Nothing to remove.")
        return 0
    record_removed(removals)
    removed = ih.remove_rows(DATA / "recently_played.csv",
                             {r["id"] for r in removals}, imported_only=False)
    assert removed == len(removals), (removed, len(removals))
    print(f"Moved {removed:,} plays to data/{REMOVED}. Now run:")
    print("  python src/database.py build && python src/database.py verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
