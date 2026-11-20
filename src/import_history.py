"""Backfill plays from a Spotify "Extended Streaming History" export.

    python src/import_history.py --zip my_spotify_data.zip \
        --since 2026-07-20 --until 2026-10-27 --dry-run

    python src/import_history.py --zip my_spotify_data.zip \
        --since 2026-07-20 --until 2026-10-27

The API only remembers roughly 50 recent plays, so anything the collector
missed is gone from it forever. The GDPR export is the one way back: it covers
the whole account, including the 98 days this pipeline was down.

The export's `ts` and the API's `played_at` mean the same thing and share the
one primary key, but they do not always agree to the second. Most plays match
within a few seconds; from May 2025 to May 2026, 11-36% a month ran 5-60s
apart, the API later. Matching therefore pairs records one to one (see
match_existing) within a two-minute window.

Skipped plays are not imported by default. The export flags them, and the API
almost never reports one: measured over the collection period, it reported 4%
of plays skipped with the next or back button and 27% of those ended by
starting something else, against 98% of plays that ran to their end. Importing
them would count, for the backfilled periods only, plays the collector would
never have seen. --include-skipped takes them anyway.

Private-session plays are never imported: the API is never told about them, by
the account holder's own choice, and this repository is public.

--prune applies the same rules backwards, removing already-imported plays that
fail them; that is how the 98-day backfill, made before skipped plays were
excluded, was cleaned.

Two fields the export simply does not carry:

  - no playlist/album/artist context, so context_type and context_id are left
    empty. An empty context is therefore the marker of an imported play; the
    database exposes it as plays_detail.source.
  - no popularity at play time, so track_popularity is left empty rather than
    backfilled with today's value, which would be a different measurement
    wearing the same name.

Records under --min-ms (default 30s) are dropped, because the API only ever
reported plays past that threshold and mixing the two would silently inflate
play counts for the imported period.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import io
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
CURRENT = REPO_ROOT / "data"
# Collected plays removed as API double-reports (src/dedupe_plays.py).
REMOVED = "removed_plays.csv"
PLAY_HEADER = ["id", "name", "track_id", "track_popularity",
               "context_type", "context_id"]

# How far apart the export and the archive may put the same play. Measured over
# the whole collection period, the gap runs continuously up to ~60s and is
# sparse beyond. The window can afford to be generous because matching is one
# to one: a genuine repeat of a track has an export record of its own, which
# claims its own row, so a wide window cannot swallow it. 15s, the old value,
# left ~6,800 already-collected plays looking new.
TOLERANCE_SECONDS = 120



def read_export(zip_path):
    """Every audio play in the export, as
    (timestamp, track_id, ms, name, skipped, private_session, reason_end).

    Nothing else is read: the export also carries IP address, platform and
    country for every play, and none of that belongs in a public repository.
    """
    records = []
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist()
                 if "Streaming_History_Audio" in n and n.endswith(".json")]
        if not names:
            raise SystemExit(
                "No Streaming_History_Audio_*.json in the archive. This needs the "
                "'Extended streaming history' export, not the basic account export.")
        for name in sorted(names):
            with archive.open(name) as handle:
                for row in json.load(io.TextIOWrapper(handle, encoding="utf-8")):
                    uri = row.get("spotify_track_uri")
                    if not uri:
                        continue  # podcast episode or audiobook chapter
                    records.append((
                        parse_ts(row["ts"]),
                        uri.rsplit(":", 1)[-1],
                        row.get("ms_played") or 0,
                        row.get("master_metadata_track_name") or "",
                        bool(row.get("skipped")),
                        bool(row.get("incognito_mode")),
                        row.get("reason_end") or "",
                    ))
    records.sort()
    return records


def parse_ts(value):
    for pattern in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    raise ValueError(f"unrecognised export timestamp: {value!r}")


def parse_day(value):
    """A window bound in UTC: a whole day, or a day and a time to the minute.

    The time form exists for filling a gap exactly. A gap rarely starts or ends
    on midnight, and widening it to whole days would also take in the edge days'
    plays the collector saw and deliberately did not record.
    """
    for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    raise ValueError(f"expected YYYY-MM-DD or YYYY-MM-DDTHH:MM, got {value!r}")


def read_current():
    with open(CURRENT / "recently_played.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows


def read_durations():
    """track_id -> length in seconds, for the tracks the archive has."""
    with open(CURRENT / "songs.csv", newline="", encoding="utf-8") as handle:
        return {r["id"]: int(r["duration_ms"] or 0) // 1000
                for r in csv.DictReader(handle) if r.get("duration_ms")}


def read_removed():
    """Plays removed as double-reports. They still claim their export segments
    when matching, or the next import would bring those segments back."""
    path = CURRENT / REMOVED
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# How export segments of one track group into listens; shared with
# dedupe_plays.py so collected and imported plays follow one rule. A listen
# interrupted (paused, handed to another device, the app closed) and resumed
# is one play, unless the pause runs past BIG_PAUSE_SECONDS. Segments adding
# up to REPEAT_COVERAGE track lengths are the track heard again: a full play
# and a short tail of it (1.1-1.5) is still one listen.
BIG_PAUSE_SECONDS = 5 * 60
REPEAT_COVERAGE = 1.6


def group_listens(segments, duration, coverage=REPEAT_COVERAGE,
                  big_pause=BIG_PAUSE_SECONDS):
    """Split one track's export segments into listens, oldest first.

    segments: tuples starting (end_ts, ms_played, ...), in any order; the
    export's ts is when a segment stopped, so it started at ts - ms_played.
    duration: the track's length in seconds; unknown (0) groups nothing.
    Returns lists of the given tuples.
    """
    segments = sorted(segments, key=lambda s: s[0])
    if duration <= 0:
        return [[s] for s in segments]
    groups = []
    for segment in segments:
        if groups:
            last = groups[-1]
            pause = segment[0] - segment[1] // 1000 - last[-1][0]
            heard = sum(s[1] for s in last) + segment[1]
            if pause <= big_pause and heard / 1000 / duration < coverage:
                last.append(segment)
                continue
        groups.append([segment])
    return groups


def match_existing(records, existing, min_ms, tolerance=TOLERANCE_SECONDS):
    """Indices of the export records that are plays the archive already has.

    One to one, per track: every archived row is paired with at most one export
    record and vice versa, closest first. Records of min_ms or more are
    preferred, since the API only ever reported those, so a nearby skip of the
    same track cannot claim a row and leave the real play looking new.
    """
    archived = {}
    for row in existing:
        archived.setdefault(row["track_id"], []).append(int(row["id"]))
    exported = {}
    for index, record in enumerate(records):
        if record[1] in archived:
            exported.setdefault(record[1], []).append(index)

    matched = set()
    for track_id, rows in archived.items():
        pairs = sorted(
            (records[i][2] < min_ms, abs(records[i][0] - row), row, i)
            for row in rows for i in exported.get(track_id, ())
            if abs(records[i][0] - row) <= tolerance)
        used = set()
        for _, _, row, i in pairs:
            if row in used or i in matched:
                continue
            used.add(row)
            matched.add(i)
    return matched


# reason_end of a play that ran to its natural end, for --whole-only.
WHOLE = "trackdone"


def rejection(record, min_ms, include_skipped=False, whole_only=False):
    """Why a record is not a play the collector could have seen, or None.

    records are read_export() tuples; the fields after the name (skipped,
    private_session, reason_end) are optional, so a bare
    (ts, track_id, ms, name) works too.
    """
    ms, extra = record[2], record[4:]
    skipped = extra[0] if extra else False
    private = extra[1] if len(extra) > 1 else False
    reason_end = extra[2] if len(extra) > 2 else WHOLE
    if ms < min_ms:
        return "too_short"
    if private:
        return "private_session"
    if skipped and not include_skipped:
        return "skipped"
    if whole_only and reason_end != WHOLE:
        return "not_whole"
    return None


def listens_of(records, durations):
    """Group export records into listens, as index lists, oldest first.

    Private-session records are left out of every listen, and each forms its
    own, so rejection() drops it. A track with no known duration groups
    nothing: every record is its own listen, as before grouping existed.
    """
    by_track = {}
    for index, record in enumerate(records):
        private = len(record) > 5 and record[5]
        if not private:
            by_track.setdefault(record[1], []).append((record[0], record[2], index))
    groups = [[i] for i, r in enumerate(records) if len(r) > 5 and r[5]]
    for track_id, segments in by_track.items():
        for group in group_listens(segments, (durations or {}).get(track_id, 0)):
            groups.append([s[2] for s in group])
    groups.sort(key=lambda g: records[g[0]][0])
    return groups


def as_listen(records, group):
    """One record standing for a whole listen: the first piece's timestamp and
    name (the collector keeps the earliest row of a doubled play too), the
    time of every piece added up, and skipped, or not run to its end, only as
    the last piece was."""
    first, last = records[group[0]], records[group[-1]]
    ms = sum(records[i][2] for i in group)
    return (first[0], first[1], ms, first[3], *last[4:5], *first[5:6], *last[6:7])


def select(records, since, until, min_ms, existing,
           tolerance=TOLERANCE_SECONDS, include_skipped=False, durations=None,
           whole_only=False):
    """Choose the listens worth importing, and say why the rest were dropped.

    With durations (track_id -> seconds), the pieces of one listen (paused,
    handed off, the app closed, then resumed) become one play, by the rule
    dedupe_plays applies to collected plays; see group_listens. Counts are of
    listens, plus merged_pieces for the records folded into another's listen.
    """
    taken_at = {int(r["id"]) for r in existing}
    already = match_existing(records, existing, min_ms, tolerance)

    chosen = []
    dropped = {"outside_window": 0, "too_short": 0, "skipped": 0,
               "private_session": 0, "already_collected": 0,
               "timestamp_taken": 0, "merged_pieces": 0, "not_whole": 0}

    for group in listens_of(records, durations):
        record = as_listen(records, group)
        ts, track_id, ms, name = record[:4]
        if (since is not None and ts < since) or (until is not None and ts >= until):
            dropped["outside_window"] += 1
            continue
        dropped["merged_pieces"] += len(group) - 1
        reason = rejection(record, min_ms, include_skipped, whole_only)
        if reason:
            dropped[reason] += 1
            continue
        if any(index in already for index in group):
            dropped["already_collected"] += 1
            continue
        if ts in taken_at:
            # A different track already owns this second, and played_at is the
            # primary key. Rare; reported rather than nudged, since moving a
            # timestamp to make room would be inventing data.
            dropped["timestamp_taken"] += 1
            continue

        taken_at.add(ts)
        chosen.append({
            "id": ts,
            "name": name,
            "track_id": track_id,
            "track_popularity": "",   # not recorded at play time
            "context_type": "",       # export carries no context
            "context_id": "",
        })

    chosen.sort(key=lambda row: row["id"])
    return chosen, dropped


def select_prunable(records, since, until, min_ms, existing, include_skipped=False,
                    tolerance=TOLERANCE_SECONDS, durations=None):
    """Imported rows that the current rules would not have imported.

    Only rows without a context are considered: those are the imported ones,
    and a collected play is never removed. An imported row carries its export
    record's exact timestamp, so the two are matched exactly, never by
    tolerance. A row is kept only if a fresh import against the collected
    plays alone would produce exactly it; so a later piece of a listen is
    pruned (merged_into_listen), as is a piece of a listen the collector has
    (already_collected). Run the importer afterwards: where the first piece of
    a listen was never imported, it adds that one in its place.
    Returns ({played_at: reason}, number of imported rows in the window with
    no export record to judge them by).
    """
    collected = [r for r in existing if r["context_type"]]
    wanted, _ = select(records, None, None, min_ms, collected, tolerance,
                       include_skipped, durations)
    wanted = {row["id"] for row in wanted}
    index_of = {(r[0], r[1]): i for i, r in enumerate(records)}
    listen_of = {}
    for group in listens_of(records, durations):
        for i in group:
            listen_of[i] = group
    already = match_existing(records, collected, min_ms, tolerance)

    prune, unmatched = {}, 0
    for row in existing:
        if row["context_type"]:
            continue
        ts = int(row["id"])
        if (since is not None and ts < since) or (until is not None and ts >= until):
            continue
        index = index_of.get((ts, row["track_id"]))
        if index is None:
            unmatched += 1
            continue
        if ts in wanted:
            continue
        group = listen_of[index]
        reason = rejection(as_listen(records, group), min_ms, include_skipped)
        if reason is None:
            reason = ("already_collected" if any(i in already for i in group)
                      else "merged_into_listen")
        prune[ts] = reason
    return prune, unmatched


def remove_rows(path, ids, imported_only=True):
    """Delete the rows whose id is in ids, leaving every other byte alone.

    The CSVs are append-only by design; this is the deliberate exception, for
    rows that should never have been imported. With imported_only, a row that
    has a context (a collected play) is refused rather than removed.
    """
    ids = {str(i) for i in ids}
    lines = Path(path).read_bytes().splitlines(keepends=True)
    header = next(csv.reader([lines[0].decode("utf-8")]))
    kept, removed = [lines[0]], 0
    for line in lines[1:]:
        fields = next(csv.reader([line.decode("utf-8")]), [])
        row = dict(zip(header, fields))
        if row.get("id") in ids:
            if imported_only and row.get("context_type"):
                raise ValueError(f"refusing to remove collected play {row['id']}")
            removed += 1
            continue
        kept.append(line)
    Path(path).write_bytes(b"".join(kept))
    return removed


def fetch_durations(track_ids):
    """track_id -> length in seconds, from the API, without storing anything."""
    import utils
    from Spotify import sp
    found = {}
    for chunk in utils.batch(list(track_ids), 50):
        for track in sp.tracks(chunk)["tracks"]:
            if track and track.get("duration_ms"):
                found[track["id"]] = track["duration_ms"] // 1000
    return found


def fetch_missing_entities(track_ids):
    """Fetch and store any songs, albums and artists we don't have yet.

    Reuses the collector's own Song/Album/Artist.store(), so imported rows are
    written by exactly the code that writes collected ones.
    """
    import utils
    from Classes import Album, Artist, Song
    from Spotify import sp
    import ReadWrite as rw

    missing = [t for t in track_ids if not rw.idExists(Song.storing_path, t)]
    print(f"  songs to fetch   : {len(missing)}")

    tracks = []
    for index, chunk in enumerate(utils.batch(missing, 50), start=1):
        tracks.extend(t for t in sp.tracks(chunk)["tracks"] if t)
        print(f"\r    tracks {len(tracks)}/{len(missing)} ({index} requests)",
              end="", flush=True)
    print()

    # Albums and artists must land first so the songs' references resolve.
    album_ids = sorted({t["album"]["id"] for t in tracks if t.get("album")})
    artist_ids = sorted({a["id"] for t in tracks for a in t.get("artists", [])})
    album_ids = [a for a in album_ids if not rw.idExists(Album.storing_path, a)]
    artist_ids = [a for a in artist_ids if not rw.idExists(Artist.storing_path, a)]
    print(f"  albums to fetch  : {len(album_ids)}")
    print(f"  artists to fetch : {len(artist_ids)}")

    stored = {"albums": 0, "artists": 0, "songs": 0}
    for index, chunk in enumerate(utils.batch(album_ids, 20), start=1):
        for album in sp.albums(chunk)["albums"]:
            if album and Album.store(album):
                stored["albums"] += 1
        print(f"\r    albums {stored['albums']}/{len(album_ids)} ({index} requests)",
              end="", flush=True)
    print()
    for index, chunk in enumerate(utils.batch(artist_ids, 50), start=1):
        for artist in sp.artists(chunk)["artists"]:
            if artist and Artist.store(artist):
                stored["artists"] += 1
        print(f"\r    artists {stored['artists']}/{len(artist_ids)} ({index} requests)",
              end="", flush=True)
    print()
    for track in tracks:
        if Song.store(track):
            stored["songs"] += 1
    print(f"  stored           : {stored}")
    return stored


def append_plays(rows, path=None):
    """Append rows, leaving every existing byte alone.

    The file mixes line endings (the collector's csv writer emits CRLF), so it
    must never be read and rewritten in text mode, which would normalise them
    and turn a 100-row import into a 1,000-line diff.
    """
    path = path or CURRENT / "recently_played.csv"
    with open(path, "rb") as handle:
        needs_newline = False
        if handle.seek(0, io.SEEK_END) > 0:
            handle.seek(-1, io.SEEK_END)
            needs_newline = handle.read(1) != b"\n"
    with open(path, "a", newline="", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=PLAY_HEADER, lineterminator="\n")
        for row in rows:
            writer.writerow(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", default="my_spotify_data.zip")
    parser.add_argument("--since", help="inclusive, YYYY-MM-DD[THH:MM] (UTC)")
    parser.add_argument("--until", help="exclusive, YYYY-MM-DD[THH:MM] (UTC)")
    parser.add_argument("--min-ms", type=int, default=30000)
    parser.add_argument("--tolerance", type=int, default=TOLERANCE_SECONDS,
                        help="seconds the export and archive may disagree on one play")
    parser.add_argument("--include-skipped", action="store_true",
                        help="also import plays the export marks as skipped")
    parser.add_argument("--whole-only", action="store_true",
                        help="only listens that ran to their end; for periods the "
                             "collector was running, where the API's own omissions "
                             "of cut-off plays are kept")
    parser.add_argument("--prune", action="store_true",
                        help="remove already-imported plays that fail these rules")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    since = parse_day(args.since) if args.since else None
    until = parse_day(args.until) if args.until else None

    records = read_export(args.zip)
    print(f"Export: {len(records):,} audio plays, "
          f"{fmt(records[0][0])} -> {fmt(records[-1][0])} UTC")

    existing = read_current() + read_removed()
    durations = read_durations()
    if args.prune:
        return prune(records, since, until, args, existing, durations)
    if not args.dry_run:
        # Grouping pieces into listens needs each track's length. For tracks
        # the archive has never seen it is looked up, not stored: songs.csv
        # holds played tracks only, and most of these will not be imported.
        window = [r for r in records if (since is None or r[0] >= since)
                  and (until is None or r[0] < until)]
        unknown = sorted({r[1] for r in window} - set(durations))
        if unknown:
            print(f"\nLooking up the length of {len(unknown):,} tracks not yet stored")
            durations = {**fetch_durations(unknown), **durations}
    chosen, dropped = select(records, since, until, args.min_ms, existing,
                             args.tolerance, args.include_skipped, durations,
                             args.whole_only)

    print(f"\nTo import: {len(chosen):,} plays")
    for reason, n in sorted(dropped.items()):
        print(f"  dropped, {reason:<18}{n:>9,}")
    if not chosen:
        print("\nNothing to import.")
        return 0

    print(f"\nWindow gained : {fmt(chosen[0]['id'])} -> {fmt(chosen[-1]['id'])} UTC")
    days = {row["id"] // 86400 for row in chosen}
    print(f"Days covered  : {len(days):,}")
    tracks = sorted({row["track_id"] for row in chosen})
    print(f"Distinct tracks: {len(tracks):,}")

    if args.dry_run:
        print("\nDry run; nothing written and no API calls made.")
        return 0

    print("\nFetching metadata for tracks we don't have:")
    fetch_missing_entities(tracks)

    append_plays(chosen)
    print(f"\nAppended {len(chosen):,} plays. Now run:")
    print("  python src/database.py build && python src/database.py verify")
    return 0


def prune(records, since, until, args, existing, durations):
    doomed, unmatched = select_prunable(records, since, until, args.min_ms,
                                        existing, args.include_skipped,
                                        args.tolerance, durations)
    print(f"\nTo remove: {len(doomed):,} imported plays")
    for reason in sorted(set(doomed.values())):
        print(f"  {reason:<18}{sum(v == reason for v in doomed.values()):>7,}")
    if unmatched:
        print(f"  ({unmatched:,} imported plays in the window have no export "
              f"record to judge them by, and are left alone)")
    if not doomed or args.dry_run:
        print("\nDry run; nothing written." if args.dry_run else "\nNothing to remove.")
        return 0
    removed = remove_rows(CURRENT / "recently_played.csv", doomed)
    inferred = CURRENT / "inferred_contexts.csv"
    gone = remove_rows(inferred, doomed, imported_only=False) if inferred.exists() else 0
    print(f"\nRemoved {removed:,} plays and {gone:,} inferred contexts. Now run:")
    print("  python src/database.py build && python src/database.py verify")
    return 0


def fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    sys.exit(main())
