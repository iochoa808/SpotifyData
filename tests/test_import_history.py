"""Tests for backfilling plays from a Spotify extended-history export.

    python -m unittest discover -s tests -v

Only the selection logic is covered here, which is where the risk is: deciding
which export records are genuinely new. Fetching metadata needs the API and is
exercised by running the importer for real.
"""
from pathlib import Path
import io
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import import_history as ih  # noqa: E402


def play(timestamp, track_id, name="Track", popularity="40",
         context_type="playlist", context_id="pl1"):
    """A row shaped like one already in recently_played.csv."""
    return {"id": str(timestamp), "name": name, "track_id": track_id,
            "track_popularity": popularity, "context_type": context_type,
            "context_id": context_id}


class TestParsing(unittest.TestCase):
    def test_parses_export_timestamps_as_utc(self):
        # Must not drift with the host timezone; played_at is the primary key.
        self.assertEqual(ih.parse_ts("2026-07-20T07:34:36Z"), 1784532876)

    def test_accepts_fractional_seconds(self):
        self.assertEqual(ih.parse_ts("2026-07-20T07:34:36.000Z"), 1784532876)

    def test_rejects_junk(self):
        with self.assertRaises(ValueError):
            ih.parse_ts("20 July 2026")

    def test_parses_day_boundaries(self):
        self.assertEqual(ih.parse_day("1970-01-02"), 86400)


class TestSelect(unittest.TestCase):
    """records are (timestamp, track_id, ms_played, name)."""

    def test_takes_a_play_we_do_not_have(self):
        chosen, dropped = ih.select([(2000, "trk1", 200000, "New")],
                                    None, None, 30000, [])
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["track_id"], "trk1")
        self.assertEqual(chosen[0]["id"], 2000)

    def test_imported_rows_leave_context_and_popularity_empty(self):
        # The export carries neither; inventing them would fabricate data.
        chosen, _ = ih.select([(2000, "trk1", 200000, "New")],
                              None, None, 30000, [])
        self.assertEqual(chosen[0]["context_type"], "")
        self.assertEqual(chosen[0]["context_id"], "")
        self.assertEqual(chosen[0]["track_popularity"], "")

    def test_skips_a_play_already_collected_at_the_same_second(self):
        chosen, dropped = ih.select([(2000, "trk1", 200000, "X")],
                                    None, None, 30000, [play(2000, "trk1")])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["already_collected"], 1)

    def test_skips_a_play_within_the_jitter_tolerance(self):
        # Export ts and API played_at disagree by up to ~3s for the same play.
        for offset in (-3, -1, 1, 3, ih.TOLERANCE_SECONDS):
            with self.subTest(offset=offset):
                chosen, dropped = ih.select(
                    [(2000 + offset, "trk1", 200000, "X")],
                    None, None, 30000, [play(2000, "trk1")])
                self.assertEqual(chosen, [], f"offset {offset} should dedup")
                self.assertEqual(dropped["already_collected"], 1)

    def test_keeps_a_genuine_repeat_play_of_the_same_track(self):
        # Beyond the tolerance it is a real second listen, not a duplicate.
        chosen, _ = ih.select([(2000 + ih.TOLERANCE_SECONDS + 1, "trk1", 200000, "X")],
                              None, None, 30000, [play(2000, "trk1")])
        self.assertEqual(len(chosen), 1)

    def test_tolerance_is_per_track_not_global(self):
        # A different track at the same instant is a different play.
        chosen, dropped = ih.select([(2001, "trk2", 200000, "Other")],
                                    None, None, 30000, [play(2000, "trk1")])
        self.assertEqual(len(chosen), 1)

    def test_refuses_to_reuse_a_taken_timestamp(self):
        # played_at is the primary key, so a different track on the same second
        # cannot be stored; nudging it would invent a play time.
        chosen, dropped = ih.select([(2000, "trk2", 200000, "Other")],
                                    None, None, 30000, [play(2000, "trk1")])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["timestamp_taken"], 1)

    def test_two_export_records_on_one_second_keep_only_the_first(self):
        chosen, dropped = ih.select(
            [(2000, "trk1", 200000, "A"), (2000, "trk2", 200000, "B")],
            None, None, 30000, [])
        self.assertEqual(len(chosen), 1)
        self.assertEqual(dropped["timestamp_taken"], 1)

    def test_drops_plays_shorter_than_the_api_threshold(self):
        # The API never reported sub-30s plays; mixing them in would inflate
        # play counts for the imported period only.
        chosen, dropped = ih.select([(2000, "trk1", 5000, "Skip")],
                                    None, None, 30000, [])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["too_short"], 1)

    def test_min_ms_is_configurable(self):
        chosen, _ = ih.select([(2000, "trk1", 5000, "Skip")],
                              None, None, 0, [])
        self.assertEqual(len(chosen), 1)

    def test_window_is_inclusive_of_since_and_exclusive_of_until(self):
        records = [(999, "a", 200000, ""), (1000, "b", 200000, ""),
                   (1999, "c", 200000, ""), (2000, "d", 200000, "")]
        chosen, dropped = ih.select(records, 1000, 2000, 30000, [])
        self.assertEqual([r["track_id"] for r in chosen], ["b", "c"])
        self.assertEqual(dropped["outside_window"], 2)

    def test_no_window_takes_everything(self):
        records = [(1, "a", 200000, ""), (10 ** 9, "b", 200000, "")]
        chosen, dropped = ih.select(records, None, None, 30000, [])
        self.assertEqual(len(chosen), 2)
        self.assertEqual(dropped["outside_window"], 0)

    def test_output_is_sorted_oldest_first(self):
        records = [(3000, "c", 200000, ""), (1000, "a", 200000, ""),
                   (2000, "b", 200000, "")]
        chosen, _ = ih.select(records, None, None, 30000, [])
        self.assertEqual([r["id"] for r in chosen], [1000, 2000, 3000])

    def test_dedups_against_an_existing_integer_keyed_csv_row(self):
        # recently_played.csv stores the key as text; select must compare ints.
        chosen, dropped = ih.select([(1784532876, "trk1", 200000, "X")],
                                    None, None, 30000,
                                    [play(1784532876, "trk1")])
        self.assertEqual(chosen, [])


class TestReadExport(unittest.TestCase):
    def archive(self, payload, name="Streaming_History_Audio_2026.json"):
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        with zipfile.ZipFile(tmp.name, "w") as archive:
            archive.writestr(f"Spotify Extended Streaming History/{name}",
                             json.dumps(payload))
        return tmp.name

    def test_reads_audio_plays(self):
        path = self.archive([{
            "ts": "2026-07-20T07:34:36Z", "ms_played": 200000,
            "spotify_track_uri": "spotify:track:abc123",
            "master_metadata_track_name": "Shimmering Scars",
        }])
        self.assertEqual(ih.read_export(path),
                         [(1784532876, "abc123", 200000, "Shimmering Scars")])

    def test_ignores_podcasts_and_audiobooks(self):
        # Those rows have no spotify_track_uri and no place in this schema.
        path = self.archive([
            {"ts": "2026-07-20T07:34:36Z", "ms_played": 200000,
             "spotify_track_uri": None, "episode_name": "Some Podcast"},
            {"ts": "2026-07-20T08:00:00Z", "ms_played": 200000,
             "spotify_track_uri": "spotify:track:keepme",
             "master_metadata_track_name": "Real Song"},
        ])
        self.assertEqual([r[1] for r in ih.read_export(path)], ["keepme"])

    def test_returns_records_sorted(self):
        path = self.archive([
            {"ts": "2026-07-20T09:00:00Z", "ms_played": 1,
             "spotify_track_uri": "spotify:track:later"},
            {"ts": "2026-07-20T07:00:00Z", "ms_played": 1,
             "spotify_track_uri": "spotify:track:earlier"},
        ])
        self.assertEqual([r[1] for r in ih.read_export(path)],
                         ["earlier", "later"])

    def test_rejects_the_basic_export(self):
        # The small account export has StreamingHistory*.json and lacks track
        # URIs entirely, so it cannot be mapped onto this schema.
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        with zipfile.ZipFile(tmp.name, "w") as archive:
            archive.writestr("MyData/StreamingHistory0.json", "[]")
        with self.assertRaises(SystemExit):
            ih.read_export(tmp.name)


if __name__ == "__main__":
    unittest.main()
