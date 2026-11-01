"""One-shot: fold the legacy data0/ dataset into the current CSVs.

    python src/migrate_data0.py --dry-run     # report what would change
    python src/migrate_data0.py               # actually append

data0/ is the first schema this project used, abandoned on 2024-12-29. It holds
2,217 plays from 14-29 December 2024 that predate every row in data/ — fifteen
days of history that exists nowhere else, since Spotify retains only the most
recent plays.

The two schemas differ, so this translates rather than copies:

    data0 played_at "2024-12-14T11:48:38.166Z"  ->  id, a UTC epoch second
    data0 context   "{'type':..., 'id':...}"    ->  context_type, context_id
    data0 album / artists columns               ->  album_id / artists_id
    data0 followers, popularity, total_albums   ->  dropped, no column for them
    tracks / images lists                       ->  empty, never collected then

Two honest losses, both recorded rather than papered over:
  - these plays have no track_popularity; the old schema kept popularity on the
    song, not the play, so the value at play time is unknown and left blank.
  - legacy albums carry no track listing and legacy artists no images, so those
    join tables simply have no rows for them.

Idempotent: rows already present are skipped, so re-running is a no-op.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import ast
import csv
import io
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY = REPO_ROOT / "data0"
CURRENT = REPO_ROOT / "data"

# The column order each current CSV already uses; appended rows must match.
HEADERS = {
    "artists": ["id", "name", "genres", "images"],
    "albums": ["id", "name", "artists_id", "tracks", "release_date", "images"],
    "songs": ["id", "name", "album_id", "artists_id", "duration_ms", "explicit",
              "isrc", "track_number"],
    "recently_played": ["id", "name", "track_id", "track_popularity",
                        "context_type", "context_id"],
}


def read(directory, name):
    path = Path(directory) / f"{name}.csv"
    for encoding in ("utf-8", "windows-1252"):
        try:
            with open(path, newline="", encoding=encoding) as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"could not decode {path}")


def to_epoch(played_at):
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(played_at, pattern)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    return None


def as_list(value):
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return []
    return parsed if isinstance(parsed, list) else []


def plan():
    """Work out exactly which rows can be added without orphaning anything."""
    legacy_plays = read(LEGACY, "recently_played")
    legacy_songs = {r["id"]: r for r in read(LEGACY, "songs")}
    legacy_albums = {r["id"]: r for r in read(LEGACY, "albums")}
    legacy_artists = {r["id"]: r for r in read(LEGACY, "artists")}

    have_plays = {int(r["id"]) for r in read(CURRENT, "recently_played")}
    have_songs = {r["id"] for r in read(CURRENT, "songs")}
    have_albums = {r["id"] for r in read(CURRENT, "albums")}
    have_artists = {r["id"] for r in read(CURRENT, "artists")}

    new_plays = []
    skipped = {"already_present": 0, "repeated_in_data0": 0,
               "unparseable": 0, "unknown_track": 0}
    need_songs = set()

    # data0 contains 39 byte-identical duplicate rows — its collector wrote
    # some plays twice. They are one play each, not two, and played_at is the
    # primary key downstream, so they have to collapse here.
    seen = set()

    for row in legacy_plays:
        when = to_epoch(row["played_at"])
        if when is None:
            skipped["unparseable"] += 1
            continue
        if when in have_plays:
            skipped["already_present"] += 1
            continue
        if when in seen:
            skipped["repeated_in_data0"] += 1
            continue
        seen.add(when)
        track = row["track"]
        if track not in have_songs and track not in legacy_songs:
            # Neither schema knows this track, so a play row would orphan.
            skipped["unknown_track"] += 1
            continue
        try:
            context = ast.literal_eval(row["context"]) if row["context"] else {}
        except (ValueError, SyntaxError):
            context = {}
        new_plays.append({
            "id": when,
            "name": (legacy_songs.get(track) or {}).get("name", ""),
            "track_id": track,
            "track_popularity": "",      # unknowable for these plays
            "context_type": context.get("type", ""),
            "context_id": context.get("id", ""),
        })
        if track not in have_songs:
            need_songs.add(track)

    # Pull in the entities those songs depend on, so every FK resolves.
    need_albums, need_artists = set(), set()
    for song_id in need_songs:
        song = legacy_songs[song_id]
        album = song.get("album")
        if album and album not in have_albums and album in legacy_albums:
            need_albums.add(album)
        for artist in as_list(song.get("artists")):
            if artist not in have_artists and artist in legacy_artists:
                need_artists.add(artist)
    for album_id in need_albums:
        for artist in as_list(legacy_albums[album_id].get("artists")):
            if artist not in have_artists and artist in legacy_artists:
                need_artists.add(artist)

    # A song whose album exists in neither dataset would break songs.album_id,
    # so drop the song and any play that depends on it.
    unresolvable = {s for s in need_songs
                    if (legacy_songs[s].get("album")
                        and legacy_songs[s]["album"] not in have_albums
                        and legacy_songs[s]["album"] not in need_albums)}
    need_songs -= unresolvable
    usable = have_songs | need_songs
    before = len(new_plays)
    new_plays = [p for p in new_plays if p["track_id"] in usable]
    skipped["unknown_album"] = before - len(new_plays)

    rows = {
        "artists": [{
            "id": legacy_artists[a]["id"],
            "name": legacy_artists[a]["name"],
            "genres": legacy_artists[a].get("genres") or "[]",
            "images": "[]",
        } for a in sorted(need_artists)],
        "albums": [{
            "id": legacy_albums[a]["id"],
            "name": legacy_albums[a]["name"],
            "artists_id": legacy_albums[a].get("artists") or "[]",
            "tracks": "[]",
            "release_date": legacy_albums[a].get("release_date") or "",
            "images": "[]",
        } for a in sorted(need_albums)],
        "songs": [{
            "id": legacy_songs[s]["id"],
            "name": legacy_songs[s]["name"],
            "album_id": legacy_songs[s].get("album") or "",
            "artists_id": legacy_songs[s].get("artists") or "[]",
            "duration_ms": legacy_songs[s].get("duration_ms") or "",
            "explicit": legacy_songs[s].get("explicit") or "False",
            "isrc": legacy_songs[s].get("isrc") or "",
            "track_number": legacy_songs[s].get("track_number") or "",
        } for s in sorted(need_songs)],
        # Oldest first, matching how the collector appends.
        "recently_played": sorted(new_plays, key=lambda p: p["id"]),
    }
    return rows, skipped


def append(name, rows):
    if not rows:
        return
    path = CURRENT / f"{name}.csv"
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS[name], lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    path.write_text(text + buffer.getvalue(), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args(argv)

    rows, skipped = plan()

    print("Rows to append to data/:")
    for name in ("artists", "albums", "songs", "recently_played"):
        print(f"  {name:<18}{len(rows[name]):>6}")
    print("\nLegacy plays not migrated:")
    for reason, n in sorted(skipped.items()):
        print(f"  {reason:<18}{n:>6}")

    if rows["recently_played"]:
        span = (rows["recently_played"][0]["id"], rows["recently_played"][-1]["id"])
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"\nHistory gained: {fmt(span[0])} -> {fmt(span[1])} UTC")

    if args.dry_run:
        print("\nDry run; nothing written.")
        return 0

    for name in ("artists", "albums", "songs", "recently_played"):
        append(name, rows[name])
    print("\nAppended. Now run:")
    print("  python src/database.py build && python src/database.py verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
