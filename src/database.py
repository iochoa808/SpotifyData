"""Build a queryable SQLite database from the collected CSVs.

    python src/database.py build      # rebuild spotify.db from data/*.csv
    python src/database.py verify     # foreign-key check + row counts vs CSVs
    python src/database.py stats      # what's in the database

The CSVs under data/ are the system of record: append-only, diffable, and
mergeable when two runs collect independently. This database is a *derived*
read model — gitignored and disposable, rebuilt from scratch in about two
seconds. Nothing in the collection pipeline reads it, so a mistake here cannot
cost a play.

Its reason to exist is the relational shape the CSVs cannot express. Roughly
58,000 album-to-track and 17,000 song-to-artist edges currently sit in the CSVs
as stringified Python lists that need ast.literal_eval and can be neither
joined nor indexed. Here they are real tables.

Which foreign keys are declared was decided by checking the data rather than by
assumption; see SCHEMA for the three relations that cannot be constrained.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import ast
import csv
import os
import sqlite3
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "spotify.db"
DEFAULT_DATA = REPO_ROOT / "data"

# Relations deliberately left unconstrained, with the orphan counts that forced
# the decision (measured 2026-11-01):
#
#   album_tracks.track_id -> songs    44,663 of 58,459 orphaned. An album lists
#       every track it contains; the collector only stores tracks actually
#       played. Most album tracks are therefore unknown, by design.
#   album_artists.artist_id -> artists    68 orphaned. Albums credit artists
#       that no played track credits, so they were never fetched.
#   plays.context_id -> playlists/albums/artists    71 of 97 playlist contexts
#       are missing: editorial playlists (37i9dQZ...) and Liked Songs are
#       skipped by Playlist.excludeStore. A constraint would reject a third of
#       the history. The column is polymorphic anyway — context_type says which
#       table it points at.
#   playlists.owner_id -> users    there is no users table; the User class has
#       never stored anything.
SCHEMA = """
CREATE TABLE artists (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE artist_genres (
    artist_id TEXT NOT NULL REFERENCES artists(id),
    genre     TEXT NOT NULL,
    PRIMARY KEY (artist_id, genre)
);

CREATE TABLE artist_images (
    artist_id TEXT    NOT NULL REFERENCES artists(id),
    position  INTEGER NOT NULL,          -- 0 is the largest Spotify returns
    url       TEXT    NOT NULL,
    PRIMARY KEY (artist_id, position)
);

CREATE TABLE albums (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    -- TEXT, not DATE: Spotify returns three precisions ('2020', '2020-04',
    -- '2020-04-10') and a DATE column would invent January 1st for the 141
    -- albums that have no day.
    release_date TEXT
);

CREATE TABLE album_artists (
    album_id  TEXT NOT NULL REFERENCES albums(id),
    artist_id TEXT NOT NULL,             -- no FK: 68 orphans, see above
    PRIMARY KEY (album_id, artist_id)
);

CREATE TABLE album_tracks (
    album_id TEXT    NOT NULL REFERENCES albums(id),
    track_id TEXT    NOT NULL,           -- no FK: 44,663 orphans, see above
    position INTEGER NOT NULL,
    PRIMARY KEY (album_id, track_id)
);

CREATE TABLE album_images (
    album_id TEXT    NOT NULL REFERENCES albums(id),
    position INTEGER NOT NULL,
    url      TEXT    NOT NULL,
    PRIMARY KEY (album_id, position)
);

CREATE TABLE songs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    album_id     TEXT REFERENCES albums(id),
    duration_ms  INTEGER,
    explicit     INTEGER CHECK (explicit IN (0, 1)),
    isrc         TEXT,
    track_number INTEGER
);

CREATE TABLE song_artists (
    song_id   TEXT    NOT NULL REFERENCES songs(id),
    artist_id TEXT    NOT NULL REFERENCES artists(id),
    position  INTEGER NOT NULL,          -- 0 is the primary credit
    PRIMARY KEY (song_id, artist_id)
);

CREATE TABLE playlists (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    collaborative INTEGER CHECK (collaborative IN (0, 1)),
    description   TEXT,
    owner_id      TEXT                   -- no FK: no users table exists
);

CREATE TABLE playlist_images (
    playlist_id TEXT    NOT NULL REFERENCES playlists(id),
    position    INTEGER NOT NULL,
    url         TEXT    NOT NULL,
    PRIMARY KEY (playlist_id, position)
);

CREATE TABLE plays (
    -- UTC epoch seconds. This is the natural key: one play per instant, and
    -- the same value the CSV uses, so the two stores stay comparable.
    played_at        INTEGER PRIMARY KEY,
    track_id         TEXT NOT NULL REFERENCES songs(id),
    -- A snapshot taken when the play was recorded, so it belongs to the play
    -- rather than to the song; the song's popularity moves over time.
    track_popularity INTEGER,
    context_type     TEXT,               -- playlist | album | artist
    context_id       TEXT                -- no FK: polymorphic, see above
);

CREATE INDEX idx_plays_track      ON plays(track_id);
CREATE INDEX idx_plays_context    ON plays(context_type, context_id);
CREATE INDEX idx_songs_album      ON songs(album_id);
CREATE INDEX idx_song_artists_art ON song_artists(artist_id);
CREATE INDEX idx_album_artists_art ON album_artists(artist_id);
CREATE INDEX idx_artist_genres    ON artist_genres(genre);
CREATE INDEX idx_album_tracks_trk ON album_tracks(track_id);

-- One row per play per crediting artist: the join every "who did I listen to"
-- question needs, and the one the stringified list column made impossible.
CREATE VIEW play_artists AS
SELECT p.played_at, sa.artist_id, sa.position
FROM plays p
JOIN song_artists sa ON sa.song_id = p.track_id;

-- Flattened play history, for ad-hoc querying without writing the joins.
CREATE VIEW plays_detail AS
SELECT p.played_at,
       datetime(p.played_at, 'unixepoch')          AS played_at_utc,
       s.id                                        AS track_id,
       s.name                                      AS track,
       (SELECT group_concat(a.name, ', ')
          FROM song_artists sa
          JOIN artists a ON a.id = sa.artist_id
         WHERE sa.song_id = s.id)                  AS artists,
       al.name                                     AS album,
       al.release_date                             AS album_release_date,
       s.duration_ms,
       s.explicit,
       p.track_popularity,
       p.context_type,
       p.context_id
FROM plays p
JOIN songs s       ON s.id = p.track_id
LEFT JOIN albums al ON al.id = s.album_id;
"""

# Table -> the CSV it is built from, for the row-count check in verify().
TABLE_SOURCE = {
    "artists": "artists",
    "albums": "albums",
    "songs": "songs",
    "playlists": "playlists",
    "plays": "recently_played",
}


def connect(db_path=DEFAULT_DB):
    """Open a connection with foreign keys on and dict-like rows."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_csv(data_dir, name):
    path = Path(data_dir) / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    # Older rows were written by a Windows runner and are not all valid UTF-8.
    for encoding in ("utf-8", "windows-1252"):
        try:
            with open(path, newline="", encoding=encoding) as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"could not decode {path}")


def as_list(value):
    """Parse a stringified Python list back into a list."""
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return []
    return parsed if isinstance(parsed, list) else []


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_bool(value):
    if value in ("True", "true", "1"):
        return 1
    if value in ("False", "false", "0"):
        return 0
    return None


def populate(conn, data_dir=DEFAULT_DATA):
    """Load every CSV into the schema. Assumes empty tables."""
    counts = {}

    artists = read_csv(data_dir, "artists")
    conn.executemany(
        "INSERT OR IGNORE INTO artists (id, name) VALUES (?, ?)",
        [(r["id"], r["name"]) for r in artists])
    conn.executemany(
        "INSERT OR IGNORE INTO artist_genres (artist_id, genre) VALUES (?, ?)",
        [(r["id"], g) for r in artists for g in as_list(r.get("genres"))])
    conn.executemany(
        "INSERT OR IGNORE INTO artist_images (artist_id, position, url) VALUES (?, ?, ?)",
        [(r["id"], i, u) for r in artists
         for i, u in enumerate(as_list(r.get("images")))])

    albums = read_csv(data_dir, "albums")
    conn.executemany(
        "INSERT OR IGNORE INTO albums (id, name, release_date) VALUES (?, ?, ?)",
        [(r["id"], r["name"], r.get("release_date") or None) for r in albums])
    conn.executemany(
        "INSERT OR IGNORE INTO album_artists (album_id, artist_id) VALUES (?, ?)",
        [(r["id"], a) for r in albums for a in as_list(r.get("artists_id"))])
    conn.executemany(
        "INSERT OR IGNORE INTO album_tracks (album_id, track_id, position) VALUES (?, ?, ?)",
        [(r["id"], t, i) for r in albums
         for i, t in enumerate(as_list(r.get("tracks")))])
    conn.executemany(
        "INSERT OR IGNORE INTO album_images (album_id, position, url) VALUES (?, ?, ?)",
        [(r["id"], i, u) for r in albums
         for i, u in enumerate(as_list(r.get("images")))])

    songs = read_csv(data_dir, "songs")
    conn.executemany(
        """INSERT OR IGNORE INTO songs
           (id, name, album_id, duration_ms, explicit, isrc, track_number)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(r["id"], r["name"], r.get("album_id") or None,
          as_int(r.get("duration_ms")), as_bool(r.get("explicit")),
          r.get("isrc") or None, as_int(r.get("track_number"))) for r in songs])
    conn.executemany(
        "INSERT OR IGNORE INTO song_artists (song_id, artist_id, position) VALUES (?, ?, ?)",
        [(r["id"], a, i) for r in songs
         for i, a in enumerate(as_list(r.get("artists_id")))])

    playlists = read_csv(data_dir, "playlists")
    conn.executemany(
        """INSERT OR IGNORE INTO playlists
           (id, name, collaborative, description, owner_id) VALUES (?, ?, ?, ?, ?)""",
        [(r["id"], r["name"], as_bool(r.get("collaborative")),
          r.get("description") or None, r.get("owner_id") or None)
         for r in playlists])
    conn.executemany(
        "INSERT OR IGNORE INTO playlist_images (playlist_id, position, url) VALUES (?, ?, ?)",
        [(r["id"], i, u) for r in playlists
         for i, u in enumerate(as_list(r.get("images")))])

    plays = read_csv(data_dir, "recently_played")
    conn.executemany(
        """INSERT OR IGNORE INTO plays
           (played_at, track_id, track_popularity, context_type, context_id)
           VALUES (?, ?, ?, ?, ?)""",
        [(as_int(r["id"]), r["track_id"], as_int(r.get("track_popularity")),
          r.get("context_type") or None, r.get("context_id") or None)
         for r in plays])

    conn.commit()

    for table in table_names(conn):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def table_names(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def build(db_path=DEFAULT_DB, data_dir=DEFAULT_DATA):
    """Rebuild the database from the CSVs.

    Builds into a temporary file and moves it into place, so an interrupted or
    failing build never leaves a half-written database behind. A full rebuild
    takes about two seconds, which is why there is no incremental sync path to
    drift out of step with the CSVs.
    """
    db_path = Path(db_path)
    temp_path = db_path.with_suffix(db_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    started = time.perf_counter()
    conn = connect(temp_path)
    try:
        conn.executescript(SCHEMA)
        counts = populate(conn, data_dir)
        problems = foreign_key_problems(conn)
        if problems:
            raise RuntimeError(
                f"{len(problems)} foreign-key violation(s) after build; "
                f"first: {dict(problems[0])}")

        # The inserts use OR IGNORE for idempotency, which also means a
        # duplicate primary key in a CSV would vanish without complaint. Build
        # from empty tables, so any shortfall is a defect in the source data
        # and must stop the build rather than wait to be noticed in verify.
        for table, source in TABLE_SOURCE.items():
            in_csv = len(read_csv(data_dir, source))
            if counts[table] != in_csv:
                raise RuntimeError(
                    f"{table}: {counts[table]} rows built from {in_csv} rows in "
                    f"{source}.csv — {in_csv - counts[table]} dropped, most "
                    f"likely a duplicate primary key")
        # Reclaim the space left by building index pages out of order, and give
        # the query planner real statistics to work with.
        conn.execute("ANALYZE")
        conn.execute("VACUUM")
    finally:
        conn.close()

    os.replace(temp_path, db_path)
    return counts, time.perf_counter() - started


def foreign_key_problems(conn):
    return conn.execute("PRAGMA foreign_key_check").fetchall()


def verify(db_path=DEFAULT_DB, data_dir=DEFAULT_DATA, report=False):
    """Check the database against the CSVs it came from. Returns a failure list."""
    failures = []
    conn = connect(db_path)
    try:
        problems = foreign_key_problems(conn)
        if problems:
            failures.append(f"{len(problems)} foreign-key violation(s)")

        for table, source in TABLE_SOURCE.items():
            in_db = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            in_csv = len(read_csv(data_dir, source))
            if report:
                status = "ok" if in_db == in_csv else "MISMATCH"
                print(f"  {table:<18} db={in_db:<8} csv={in_csv:<8} {status}")
            if in_db != in_csv:
                failures.append(f"{table}: {in_db} rows vs {in_csv} in {source}.csv")
    finally:
        conn.close()
    return failures


def stats(db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        print(f"  {'table':<18}{'rows':>10}")
        for table in table_names(conn):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<18}{n:>10,}")
        first, last, total = conn.execute(
            "SELECT MIN(played_at), MAX(played_at), COUNT(*) FROM plays").fetchone()
        if first:
            fmt = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime(
                "%Y-%m-%d %H:%M")
            print(f"\n  history: {total:,} plays from {fmt(first)} to {fmt(last)} UTC")
        print(f"  file: {Path(db_path).stat().st_size / 1e6:.1f} MB")
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build", "verify", "stats"],
                        nargs="?", default="build")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    args = parser.parse_args(argv)

    if args.command == "build":
        counts, elapsed = build(args.db, args.data)
        print(f"Built {args.db} in {elapsed:.1f}s")
        for table, n in sorted(counts.items()):
            print(f"  {table:<18}{n:>10,}")
        return 0

    if args.command == "verify":
        print(f"Verifying {args.db} against {args.data}/")
        failures = verify(args.db, args.data, report=True)
        if failures:
            print("\nFAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nAll checks passed.")
        return 0

    stats(args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
