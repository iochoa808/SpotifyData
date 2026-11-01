"""Backfill plays from a Spotify "Extended Streaming History" export.

    python src/import_history.py --zip my_spotify_data.zip \
        --since 2026-07-20 --until 2026-10-27 --dry-run

    python src/import_history.py --zip my_spotify_data.zip \
        --since 2026-07-20 --until 2026-10-27

The API only remembers roughly 50 recent plays, so anything the collector
missed is gone from it forever. The GDPR export is the one way back: it covers
the whole account, including the 98 days this pipeline was down.

Timestamp semantics were calibrated against 50,212 plays this project collected
independently: the export's `ts` and the API's `played_at` agree exactly for
most plays and within three seconds for the rest, so they mean the same thing
and can share the one primary key. Matching uses a small tolerance for that
jitter.

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
PLAY_HEADER = ["id", "name", "track_id", "track_popularity",
               "context_type", "context_id"]

# Export ts and API played_at drift by up to ~3s for the same play; 15s is a
# comfortable margin that still cannot swallow a genuine repeat play, since a
# track has to finish before it can be recorded again.
TOLERANCE_SECONDS = 15


def read_export(zip_path):
    """Every audio play in the export, as (timestamp, track_id, ms, name)."""
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
    return int(datetime.strptime(value, "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


def read_current():
    with open(CURRENT / "recently_played.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows


def select(records, since, until, min_ms, existing):
    """Choose the records worth importing, and say why the rest were dropped."""
    taken_at = {int(r["id"]) for r in existing}
    # Same track, roughly the same moment -> the play we already have.
    by_track = {}
    for row in existing:
        by_track.setdefault(row["track_id"], []).append(int(row["id"]))

    chosen = []
    dropped = {"outside_window": 0, "too_short": 0,
               "already_collected": 0, "timestamp_taken": 0}

    for ts, track_id, ms, name in records:
        if (since is not None and ts < since) or (until is not None and ts >= until):
            dropped["outside_window"] += 1
            continue
        if ms < min_ms:
            dropped["too_short"] += 1
            continue
        if any(abs(ts - other) <= TOLERANCE_SECONDS
               for other in by_track.get(track_id, ())):
            dropped["already_collected"] += 1
            continue
        if ts in taken_at:
            # A different track already owns this second, and played_at is the
            # primary key. Rare; reported rather than nudged, since moving a
            # timestamp to make room would be inventing data.
            dropped["timestamp_taken"] += 1
            continue

        taken_at.add(ts)
        by_track.setdefault(track_id, []).append(ts)
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


def append_plays(rows):
    path = CURRENT / "recently_played.csv"
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PLAY_HEADER, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    path.write_text(text + buffer.getvalue(), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", default="my_spotify_data.zip")
    parser.add_argument("--since", help="inclusive, YYYY-MM-DD (UTC)")
    parser.add_argument("--until", help="exclusive, YYYY-MM-DD (UTC)")
    parser.add_argument("--min-ms", type=int, default=30000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    since = parse_day(args.since) if args.since else None
    until = parse_day(args.until) if args.until else None

    records = read_export(args.zip)
    print(f"Export: {len(records):,} audio plays, "
          f"{fmt(records[0][0])} -> {fmt(records[-1][0])} UTC")

    existing = read_current()
    chosen, dropped = select(records, since, until, args.min_ms, existing)

    print(f"\nTo import: {len(chosen):,} plays")
    for reason, n in sorted(dropped.items()):
        print(f"  dropped, {reason:<18}{n:>8,}")
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


def fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    sys.exit(main())
