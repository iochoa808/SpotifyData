"""Regression tests for the collection pipeline.

Run from the repository root:

    python -m unittest discover -s tests -v

Deliberately stdlib-only and credential-free: these have to run in CI on a
branch where no Spotify secret is available.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ReadWrite as rw  # noqa: E402
import utils  # noqa: E402


class SwitchTimeZone:
    """Run a block as if the machine were in another zone."""

    def __init__(self, name):
        self.name = name
        self.previous = os.environ.get("TZ")

    def __enter__(self):
        os.environ["TZ"] = self.name
        time.tzset()

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.previous
        time.tzset()


class TestToTimestamp(unittest.TestCase):
    """The play timestamp is the primary key, so it must not move with the host.

    Reading Spotify's UTC string in local time silently forked the history
    whenever the collector ran outside the UTC CI runner.
    """

    # The final row written by CI before the pipeline broke; known good.
    SPOTIFY_TIME = "2026-07-20T07:34:36.000Z"
    EPOCH = 1784532876

    def test_matches_known_good_row(self):
        self.assertEqual(utils.toTimestamp(self.SPOTIFY_TIME), self.EPOCH)

    def test_identical_in_every_timezone(self):
        for zone in ("UTC", "Europe/Madrid", "America/New_York", "Asia/Tokyo",
                     "Australia/Eucla"):
            with self.subTest(zone=zone), SwitchTimeZone(zone):
                self.assertEqual(utils.toTimestamp(self.SPOTIFY_TIME), self.EPOCH)

    def test_accepts_both_spotify_formats(self):
        with_millis = utils.toTimestamp("2026-07-20T07:34:36.000Z")
        without_millis = utils.toTimestamp("2026-07-20T07:34:36Z")
        self.assertEqual(with_millis, without_millis)

    def test_rejects_unparseable_input(self):
        # Previously a bare `except:` swallowed this into a second failed parse.
        with self.assertRaises(ValueError):
            utils.toTimestamp("20 July 2026")


class TestToDateTime(unittest.TestCase):
    def test_roundtrips_and_is_timezone_aware(self):
        moment = utils.toDateTime(TestToTimestamp.EPOCH)
        self.assertIsNotNone(moment.tzinfo)
        self.assertEqual(int(moment.timestamp()), TestToTimestamp.EPOCH)

    def test_same_instant_regardless_of_zone(self):
        with SwitchTimeZone("Asia/Tokyo"):
            tokyo = utils.toDateTime(TestToTimestamp.EPOCH)
        with SwitchTimeZone("UTC"):
            utc = utils.toDateTime(TestToTimestamp.EPOCH)
        self.assertEqual(tokyo.astimezone(timezone.utc),
                         utc.astimezone(timezone.utc))


class Row:
    """Minimal stand-in for a SpotifyObject; saveInstanceToCSV reads vars()."""

    def __init__(self, id, name):
        self.id = id
        self.name = name


class TestCsvStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._real_data = rw.DATA
        rw.DATA = self.tmp.name
        rw._id_cache.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        rw.DATA = self._real_data
        rw._id_cache.clear()

    def test_round_trip(self):
        rw.saveInstanceToCSV(Row("4cOdK2wGLETKBW3PvgPWqT", "Never Gonna"), "songs.csv")
        self.assertTrue(rw.idExists("songs.csv", "4cOdK2wGLETKBW3PvgPWqT"))
        stored = rw.instanceExists("songs.csv", "4cOdK2wGLETKBW3PvgPWqT")
        self.assertEqual(stored["name"], "Never Gonna")

    def test_unknown_id_is_absent(self):
        rw.saveInstanceToCSV(Row("aaa", "a"), "songs.csv")
        self.assertFalse(rw.idExists("songs.csv", "zzz"))

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(rw.loadIds("does_not_exist.csv"), set())
        self.assertIsNone(rw.latestId("does_not_exist.csv"))

    def test_cache_tracks_writes_without_rereading(self):
        rw.loadIds("songs.csv")  # prime the cache while the file is absent
        rw.saveInstanceToCSV(Row("newid", "fresh"), "songs.csv")
        self.assertTrue(rw.idExists("songs.csv", "newid"))

    def test_latest_id_ignores_file_order(self):
        # recently_played.csv is append-ordered, not sorted: 32 adjacent pairs
        # in the real file are out of order, so the last line is not the newest.
        for timestamp in (1784532876, 1784500000, 1784599999, 1784400000):
            rw.saveInstanceToCSV(Row(timestamp, "play"), "recently_played.csv")
        self.assertEqual(rw.latestId("recently_played.csv"), 1784599999)

    def test_integer_keys_survive_the_round_trip(self):
        rw.saveInstanceToCSV(Row(1784532876, "play"), "recently_played.csv")
        # Written as text, read back as int — otherwise every play looks new.
        self.assertTrue(rw.idExists("recently_played.csv", 1784532876))


class TestParseValue(unittest.TestCase):
    def test_types(self):
        self.assertEqual(rw.parse_value("123"), 123)
        self.assertEqual(rw.parse_value("1.5"), 1.5)
        self.assertIs(rw.parse_value("True"), True)
        self.assertIs(rw.parse_value("false"), False)
        self.assertEqual(rw.parse_value("['a', 'b']"), ["a", "b"])
        self.assertEqual(rw.parse_value("plain"), "plain")

    def test_spotify_id_stays_a_string(self):
        # A 22-char id of only digits must not become an int.
        self.assertEqual(rw.parse_value("4cOdK2wGLETKBW3PvgPWqT"),
                         "4cOdK2wGLETKBW3PvgPWqT")


class TestNestedLookup(unittest.TestCase):
    def test_flattens_dotted_paths(self):
        track = {"external_ids": {"isrc": "GBAYE0601498"}}
        self.assertEqual(
            utils.getValueFromNestedDictionary(track, "external_ids.isrc"),
            "GBAYE0601498")

    def test_maps_over_lists(self):
        track = {"artists": [{"id": "a1"}, {"id": "a2"}]}
        self.assertEqual(utils.getValueFromNestedDictionary(track, "artists.id"),
                         ["a1", "a2"])

    def test_missing_key_is_none(self):
        self.assertIsNone(utils.getValueFromNestedDictionary({"a": 1}, "b.c"))


class TestBatch(unittest.TestCase):
    def test_respects_api_chunk_limits(self):
        # /v1/albums caps at 20 ids per request, /v1/tracks and /v1/artists at 50.
        self.assertEqual([len(b) for b in utils.batch(range(45), 20)], [20, 20, 5])

    def test_empty_input_yields_nothing(self):
        self.assertEqual(list(utils.batch([], 20)), [])


if __name__ == "__main__":
    unittest.main()
