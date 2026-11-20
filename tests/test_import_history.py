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

    def test_window_bounds_accept_a_time(self):
        self.assertEqual(ih.parse_day("1970-01-02T01:30"), 86400 + 5400)
        self.assertEqual(ih.parse_day("1970-01-02 01:30"), 86400 + 5400)

    def test_window_bounds_reject_junk(self):
        with self.assertRaises(ValueError):
            ih.parse_day("2 Jan 1970")


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


class TestMatching(unittest.TestCase):
    """The archive's timestamp for a play can trail the export's by up to a
    minute; matching has to pair them without swallowing real repeats."""

    def test_drift_inside_the_tolerance_is_the_same_play(self):
        chosen, dropped = ih.select([(2000, "trk1", 200000, "X")],
                                    None, None, 30000, [play(2045, "trk1")])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["already_collected"], 1)

    def test_one_archived_row_claims_only_one_export_record(self):
        # Two listens a track-length apart, one of them collected: the other
        # is a genuine repeat, inside the window though it is.
        chosen, _ = ih.select([(2000, "trk1", 60000, "X"), (2065, "trk1", 60000, "X")],
                              None, None, 30000, [play(2066, "trk1")])
        self.assertEqual([r["id"] for r in chosen], [2000])

    def test_closest_record_claims_the_row(self):
        chosen, _ = ih.select([(1900, "trk1", 60000, "X"), (1995, "trk1", 60000, "X")],
                              None, None, 30000, [play(2000, "trk1")])
        self.assertEqual([r["id"] for r in chosen], [1900])

    def test_a_nearby_skip_cannot_claim_the_row(self):
        # The skip is closer, but the API only reports plays of 30s or more,
        # so the row is the full play's.
        chosen, dropped = ih.select(
            [(1990, "trk1", 200000, "X"), (2000, "trk1", 4000, "X")],
            None, None, 30000, [play(2001, "trk1")])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["already_collected"], 1)
        self.assertEqual(dropped["too_short"], 1)

    def test_tolerance_is_configurable(self):
        chosen, _ = ih.select([(2000, "trk1", 200000, "X")],
                              None, None, 30000, [play(2045, "trk1")], tolerance=15)
        self.assertEqual(len(chosen), 1)


class TestFilters(unittest.TestCase):
    def test_private_session_plays_are_never_imported(self):
        chosen, dropped = ih.select([(2000, "trk1", 200000, "X", False, True)],
                                    None, None, 30000, [])
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["private_session"], 1)

    RECORDS = [(2000, "a", 200000, "X", False, False),
               (3000, "b", 200000, "X", True, False)]

    def test_skipped_plays_are_dropped_by_default(self):
        # The API almost never reports a skipped play, so importing them would
        # inflate the backfilled periods only.
        chosen, dropped = ih.select(self.RECORDS, None, None, 30000, [])
        self.assertEqual([r["track_id"] for r in chosen], ["a"])
        self.assertEqual(dropped["skipped"], 1)

    def test_include_skipped_takes_them(self):
        chosen, _ = ih.select(self.RECORDS, None, None, 30000, [],
                              include_skipped=True)
        self.assertEqual(len(chosen), 2)


class TestPrune(unittest.TestCase):
    RECORDS = [(1000, "a", 200000, "A", False, False),
               (2000, "b", 200000, "B", True, False),     # skipped
               (3000, "c", 10000, "C", False, False),     # too short
               (4000, "d", 200000, "D", True, False)]     # skipped, but collected

    def test_selects_imported_rows_the_rules_now_reject(self):
        existing = [play(1000, "a", context_type=""), play(2000, "b", context_type=""),
                    play(3000, "c", context_type=""), play(4000, "d")]
        doomed, unmatched = ih.select_prunable(self.RECORDS, None, None, 30000, existing)
        self.assertEqual(doomed, {2000: "skipped", 3000: "too_short"})
        self.assertEqual(unmatched, 0)

    def test_never_selects_a_collected_play(self):
        doomed, _ = ih.select_prunable(self.RECORDS, None, None, 30000, [play(4000, "d")])
        self.assertEqual(doomed, {})

    def test_matches_exactly_not_by_tolerance(self):
        # An imported row is the export record itself; a near miss is not it.
        doomed, unmatched = ih.select_prunable(
            self.RECORDS, None, None, 30000, [play(2001, "b", context_type="")])
        self.assertEqual((doomed, unmatched), ({}, 1))

    def test_respects_the_window(self):
        existing = [play(2000, "b", context_type="")]
        doomed, _ = ih.select_prunable(self.RECORDS, 2001, None, 30000, existing)
        self.assertEqual(doomed, {})

    def remove(self, content, ids, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recently_played.csv"
            path.write_bytes(content)
            n = ih.remove_rows(path, ids, **kwargs)
            return n, path.read_bytes()

    def test_removes_rows_and_leaves_every_other_byte(self):
        content = (b"id,name,track_id,track_popularity,context_type,context_id\n"
                   b"1,\"A, live\",a,40,album,x\r\n"
                   b"2,B,b,,,\n"
                   b"3,C,c,40,playlist,y\r\n")
        n, after = self.remove(content, {2})
        self.assertEqual(n, 1)
        self.assertEqual(after, content.replace(b"2,B,b,,,\n", b""))

    def test_refuses_to_remove_a_collected_play(self):
        content = (b"id,name,track_id,track_popularity,context_type,context_id\n"
                   b"1,A,a,40,album,x\n")
        with self.assertRaises(ValueError):
            self.remove(content, {1})


class TestListens(unittest.TestCase):
    """Pieces of one listen import as one play, by dedupe_plays' rule.
    Records are (end_ts, track, ms, name, skipped, private); the track is 200s."""

    DUR = {"t": 200}

    def test_group_listens_merges_pieces_after_a_short_pause(self):
        groups = ih.group_listens([(1000, 140000), (1120, 60000)], 200)
        self.assertEqual(len(groups), 1)

    def test_group_listens_splits_on_a_big_pause(self):
        pause = ih.BIG_PAUSE_SECONDS + 1
        groups = ih.group_listens([(1000, 100000), (1000 + pause + 100, 100000)], 200)
        self.assertEqual(len(groups), 2)

    def test_group_listens_splits_when_the_track_is_heard_again(self):
        groups = ih.group_listens([(1000, 200000), (1200, 200000), (1400, 200000)], 200)
        self.assertEqual(len(groups), 3)

    def test_group_listens_keeps_a_short_tail_in_the_listen(self):
        self.assertEqual(len(ih.group_listens([(1000, 200000), (1020, 20000)], 200)), 1)

    def test_unknown_duration_groups_nothing(self):
        self.assertEqual(len(ih.group_listens([(1000, 140000), (1120, 60000)], 0)), 2)

    def test_pieces_import_as_one_play_at_the_first_piece(self):
        records = [(1000, "t", 140000, "T", False, False),
                   (1120, "t", 60000, "T", False, False)]
        chosen, dropped = ih.select(records, None, None, 30000, [], durations=self.DUR)
        self.assertEqual([r["id"] for r in chosen], [1000])
        self.assertEqual(dropped["merged_pieces"], 1)

    def test_short_pieces_add_up_past_the_threshold(self):
        # Neither piece reaches 30s alone; the listen does.
        records = [(1000, "t", 20000, "T", False, False),
                   (1030, "t", 20000, "T", False, False)]
        chosen, _ = ih.select(records, None, None, 30000, [], durations=self.DUR)
        self.assertEqual([r["id"] for r in chosen], [1000])

    def test_a_listen_is_skipped_if_its_last_piece_was(self):
        records = [(1000, "t", 100000, "T", False, False),
                   (1030, "t", 20000, "T", True, False)]
        chosen, dropped = ih.select(records, None, None, 30000, [], durations=self.DUR)
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["skipped"], 1)

    def test_a_listen_with_any_collected_piece_is_collected(self):
        records = [(1000, "t", 140000, "T", False, False),
                   (1120, "t", 60000, "T", False, False)]
        chosen, dropped = ih.select(records, None, None, 30000, [play(1121, "t")],
                                    durations=self.DUR)
        self.assertEqual(chosen, [])
        self.assertEqual(dropped["already_collected"], 1)

    def test_whole_only_judges_how_the_listen_ended(self):
        # Cut off by the app closing, then resumed and run to the end: whole.
        records = [(1000, "t", 140000, "T", False, False, "logout"),
                   (1120, "t", 60000, "T", False, False, "trackdone"),
                   (5000, "t", 60000, "T", False, False, "logout")]
        chosen, dropped = ih.select(records, None, None, 30000, [],
                                    durations=self.DUR, whole_only=True)
        self.assertEqual([r["id"] for r in chosen], [1000])
        self.assertEqual(dropped["not_whole"], 1)

    def test_a_repeat_imports_twice(self):
        records = [(1000, "t", 200000, "T", False, False),
                   (1200, "t", 200000, "T", False, False)]
        chosen, _ = ih.select(records, None, None, 30000, [], durations=self.DUR)
        self.assertEqual(len(chosen), 2)

    def test_prune_removes_later_pieces_imported_separately(self):
        records = [(1000, "t", 140000, "T", False, False),
                   (1120, "t", 60000, "T", False, False)]
        existing = [play(1000, "t", context_type=""), play(1120, "t", context_type="")]
        doomed, _ = ih.select_prunable(records, None, None, 30000, existing,
                                       durations=self.DUR)
        self.assertEqual(doomed, {1120: "merged_into_listen"})

    def test_prune_removes_pieces_of_a_collected_listen(self):
        records = [(1000, "t", 140000, "T", False, False),
                   (1120, "t", 60000, "T", False, False)]
        existing = [play(1001, "t"), play(1120, "t", context_type="")]
        doomed, _ = ih.select_prunable(records, None, None, 30000, existing,
                                       durations=self.DUR)
        self.assertEqual(doomed, {1120: "already_collected"})


class TestAppendPlays(unittest.TestCase):
    def append_to(self, existing):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recently_played.csv"
            path.write_bytes(existing)
            ih.append_plays([{"id": 3, "name": "C", "track_id": "t3",
                              "track_popularity": "", "context_type": "",
                              "context_id": ""}], path)
            return path.read_bytes()

    def test_leaves_existing_crlf_rows_untouched(self):
        existing = b"id,name\n1,A\r\n2,B\r\n"
        self.assertEqual(self.append_to(existing), existing + b"3,C,t3,,,\n")

    def test_terminates_an_unterminated_last_line(self):
        self.assertEqual(self.append_to(b"id,name\n1,A"),
                         b"id,name\n1,A\n3,C,t3,,,\n")


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
            "reason_end": "trackdone", "skipped": False, "incognito_mode": False,
            "ip_addr": "203.0.113.9", "platform": "linux", "conn_country": "ES",
        }])
        # Only these six fields: the identifying ones must never be read.
        self.assertEqual(ih.read_export(path),
                         [(1784532876, "abc123", 200000, "Shimmering Scars",
                           False, False, "trackdone")])

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
