"""Tests for the derived SQLite read model.

    python -m unittest discover -s tests -v

Built against a small synthetic fixture rather than the real 48k-row CSVs, so
the suite stays fast and credential-free. The fixture deliberately contains the
awkward shapes the real data has: a multi-artist song, a multi-genre artist,
image lists, an album listing tracks that were never played, and an album
crediting an artist that was never fetched.
"""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database as db  # noqa: E402

FIXTURE = {
    "artists": (
        "id,name,genres,images\n"
        "art1,Vulfpeck,\"['funk', 'jazz funk']\",\"['https://i/a1-large', 'https://i/a1-small']\"\n"
        "art2,Remi Wolf,['indie pop'],['https://i/a2-large']\n"
    ),
    "albums": (
        "id,name,artists_id,tracks,release_date,images\n"
        # lists three tracks; only two are ever stored as songs
        "alb1,Hill Climber,['art1'],\"['sng1', 'sng2', 'never-played']\",2018-11-16,['https://i/alb1']\n"
        # credits art9, which is not in artists.csv - the real data has 68 of these
        "alb2,Juno,\"['art2', 'art9']\",['sng3'],2021,['https://i/alb2']\n"
    ),
    "songs": (
        "id,name,album_id,artists_id,duration_ms,explicit,isrc,track_number\n"
        "sng1,Darwin Derby,alb1,['art1'],201000,False,US123,1\n"
        # two credited artists - the edge the stringified list made unjoinable
        "sng2,Lonely Town,alb1,\"['art1', 'art2']\",188000,True,US124,2\n"
        "sng3,Cinderella,alb2,['art2'],215000,False,US125,3\n"
    ),
    "playlists": (
        "id,name,collaborative,description,owner_id\n"
        "pl1,Funk,False,\"groove, mostly\",iski08\n"
    ),
    "recently_played": (
        "id,name,track_id,track_popularity,context_type,context_id\n"
        "1700000000,Darwin Derby,sng1,40,playlist,pl1\n"
        "1700000200,Lonely Town,sng2,55,album,alb1\n"
        # an editorial playlist that is deliberately never stored
        "1700000400,Cinderella,sng3,61,playlist,37i9dQZF1DXnotstored\n"
    ),
}


def write_fixture(directory, overrides=None):
    data = dict(FIXTURE)
    data.update(overrides or {})
    for name, text in data.items():
        (Path(directory) / f"{name}.csv").write_text(text, encoding="utf-8")


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self.db = Path(self.tmp.name) / "test.db"
        write_fixture(self.data)

    def build(self):
        return db.build(self.db, self.data)


class TestBuild(DatabaseTestCase):
    def test_creates_every_table_and_view(self):
        self.build()
        conn = db.connect(self.db)
        self.addCleanup(conn.close)
        tables = set(db.table_names(conn))
        self.assertEqual(tables, {
            "artists", "artist_genres", "artist_images",
            "albums", "album_artists", "album_tracks", "album_images",
            "songs", "song_artists",
            "playlists", "playlist_images", "plays",
        })
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")}
        self.assertEqual(views, {"play_artists", "plays_detail"})

    def test_row_counts_match_the_csvs(self):
        counts, _ = self.build()
        self.assertEqual(counts["artists"], 2)
        self.assertEqual(counts["albums"], 2)
        self.assertEqual(counts["songs"], 3)
        self.assertEqual(counts["playlists"], 1)
        self.assertEqual(counts["plays"], 3)

    def test_verify_passes_on_a_fresh_build(self):
        self.build()
        self.assertEqual(db.verify(self.db, self.data), [])

    def test_no_foreign_key_violations(self):
        self.build()
        conn = db.connect(self.db)
        self.addCleanup(conn.close)
        self.assertEqual(db.foreign_key_problems(conn), [])

    def test_building_twice_is_idempotent(self):
        first, _ = self.build()
        second, _ = self.build()
        self.assertEqual(first, second)

    def test_leaves_no_temp_file_behind(self):
        self.build()
        self.assertFalse(self.db.with_suffix(".db.tmp").exists())


class TestNormalisation(DatabaseTestCase):
    """The point of the whole exercise: list columns become joinable rows."""

    def setUp(self):
        super().setUp()
        self.build()
        self.conn = db.connect(self.db)
        self.addCleanup(self.conn.close)

    def one(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_multi_artist_song_becomes_two_rows(self):
        self.assertEqual(
            self.one("SELECT COUNT(*) FROM song_artists WHERE song_id='sng2'"), 2)

    def test_credit_order_is_preserved(self):
        rows = self.conn.execute(
            "SELECT artist_id FROM song_artists WHERE song_id='sng2' ORDER BY position"
        ).fetchall()
        self.assertEqual([r[0] for r in rows], ["art1", "art2"])

    def test_multi_genre_artist_becomes_two_rows(self):
        self.assertEqual(
            self.one("SELECT COUNT(*) FROM artist_genres WHERE artist_id='art1'"), 2)

    def test_image_lists_are_split_and_ordered(self):
        rows = self.conn.execute(
            "SELECT url FROM artist_images WHERE artist_id='art1' ORDER BY position"
        ).fetchall()
        self.assertEqual([r[0] for r in rows],
                         ["https://i/a1-large", "https://i/a1-small"])

    def test_album_tracks_keeps_tracks_that_were_never_played(self):
        # 44,663 of 58,459 real edges point at unplayed tracks; dropping them
        # would silently discard most of an album's contents.
        self.assertEqual(self.one("SELECT COUNT(*) FROM album_tracks WHERE album_id='alb1'"), 3)
        self.assertEqual(
            self.one("SELECT COUNT(*) FROM album_tracks t "
                     "LEFT JOIN songs s ON s.id=t.track_id WHERE s.id IS NULL"), 1)

    def test_album_can_credit_an_unfetched_artist(self):
        # The real data has 68 of these, so album_artists.artist_id has no FK.
        self.assertEqual(
            self.one("SELECT COUNT(*) FROM album_artists WHERE artist_id='art9'"), 1)

    def test_unstored_context_is_kept_not_dropped(self):
        # Editorial playlists are skipped by excludeStore but still played.
        self.assertEqual(
            self.one("SELECT COUNT(*) FROM plays WHERE context_id LIKE '37i9dQZ%'"), 1)

    def test_explicit_is_stored_as_a_constrained_integer(self):
        self.assertEqual(self.one("SELECT explicit FROM songs WHERE id='sng2'"), 1)
        self.assertEqual(self.one("SELECT explicit FROM songs WHERE id='sng1'"), 0)

    def test_partial_release_date_is_preserved_verbatim(self):
        # '2021' must not become '2021-01-01'.
        self.assertEqual(self.one("SELECT release_date FROM albums WHERE id='alb2'"), "2021")

    def test_description_containing_a_comma_survives(self):
        self.assertEqual(
            self.one("SELECT description FROM playlists WHERE id='pl1'"), "groove, mostly")


class TestViews(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.build()
        self.conn = db.connect(self.db)
        self.addCleanup(self.conn.close)

    def test_play_artists_fans_out_a_multi_artist_play(self):
        # sng2 has two credits, so its single play yields two artist rows.
        rows = self.conn.execute(
            "SELECT artist_id FROM play_artists WHERE played_at=1700000200 "
            "ORDER BY position").fetchall()
        self.assertEqual([r[0] for r in rows], ["art1", "art2"])

    def test_plays_detail_joins_names_together(self):
        row = self.conn.execute(
            "SELECT * FROM plays_detail WHERE played_at=1700000200").fetchone()
        self.assertEqual(row["track"], "Lonely Town")
        self.assertEqual(row["album"], "Hill Climber")
        self.assertEqual(row["artists"], "Vulfpeck, Remi Wolf")
        self.assertEqual(row["played_at_utc"], "2023-11-14 22:16:40")

    def test_artist_play_counts_are_now_a_group_by(self):
        rows = self.conn.execute("""
            SELECT a.name, COUNT(*) AS plays
            FROM play_artists pa JOIN artists a ON a.id = pa.artist_id
            GROUP BY a.id ORDER BY plays DESC, a.name""").fetchall()
        # Both have two plays, so the a.name tiebreak decides the order.
        self.assertEqual([(r[0], r[1]) for r in rows],
                         [("Remi Wolf", 2), ("Vulfpeck", 2)])


class TestFailureHandling(DatabaseTestCase):
    def test_a_play_referencing_an_unknown_track_fails_the_build(self):
        write_fixture(self.data, {
            "recently_played": (
                "id,name,track_id,track_popularity,context_type,context_id\n"
                "1700000000,Ghost,does-not-exist,40,playlist,pl1\n"
            )})
        with self.assertRaises(sqlite3.IntegrityError):
            self.build()

    def test_a_failed_build_does_not_destroy_the_previous_database(self):
        self.build()
        before = self.db.read_bytes()
        write_fixture(self.data, {
            "recently_played": (
                "id,name,track_id,track_popularity,context_type,context_id\n"
                "1700000000,Ghost,does-not-exist,40,playlist,pl1\n"
            )})
        with self.assertRaises(sqlite3.IntegrityError):
            self.build()
        # The build writes to a temp file and moves it, so the good one survives.
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(db.verify(self.db, self.data), [
            "plays: 3 rows vs 1 in recently_played.csv"])

    def test_missing_csv_is_reported_clearly(self):
        (self.data / "songs.csv").unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()

    def test_verify_reports_a_count_mismatch(self):
        self.build()
        with open(self.data / "recently_played.csv", "a", encoding="utf-8") as handle:
            handle.write("1700000600,Darwin Derby,sng1,40,playlist,pl1\n")
        failures = db.verify(self.db, self.data)
        self.assertEqual(failures, ["plays: 3 rows vs 4 in recently_played.csv"])


class TestHelpers(unittest.TestCase):
    def test_as_list(self):
        self.assertEqual(db.as_list("['a', 'b']"), ["a", "b"])
        self.assertEqual(db.as_list(""), [])
        self.assertEqual(db.as_list(None), [])
        self.assertEqual(db.as_list("not a list"), [])
        self.assertEqual(db.as_list("'bare string'"), [])

    def test_as_int(self):
        self.assertEqual(db.as_int("42"), 42)
        self.assertIsNone(db.as_int(""))
        self.assertIsNone(db.as_int("abc"))
        self.assertIsNone(db.as_int(None))

    def test_as_bool(self):
        self.assertEqual(db.as_bool("True"), 1)
        self.assertEqual(db.as_bool("False"), 0)
        self.assertIsNone(db.as_bool(""))


if __name__ == "__main__":
    unittest.main()
