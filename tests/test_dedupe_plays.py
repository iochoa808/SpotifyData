"""Tests for removing plays the API reported twice.

    python -m unittest discover -s tests -v
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import dedupe_plays as dd  # noqa: E402


def row(ts, track="t", context="album"):
    return {"id": str(ts), "name": "N", "track_id": track, "track_popularity": "40",
            "context_type": context, "context_id": "c" if context else ""}


DUR = {"t": 200, "u": 200}


class TestChains(unittest.TestCase):
    def test_rows_closer_than_the_track_form_a_chain(self):
        found = list(dd.chains([row(0), row(100)], DUR))
        self.assertEqual([[r["id"] for r in c] for c in found], [["0", "100"]])

    def test_rows_a_track_length_apart_are_two_listens(self):
        self.assertEqual(list(dd.chains([row(0), row(200)], DUR)), [])

    def test_the_margin_allows_for_rounding(self):
        self.assertEqual(list(dd.chains([row(0), row(196)], DUR)), [])

    def test_a_chain_can_be_longer_than_two(self):
        found = list(dd.chains([row(0), row(50), row(100), row(400)], DUR))
        self.assertEqual([len(c) for c in found], [3])

    def test_different_tracks_never_chain(self):
        self.assertEqual(list(dd.chains([row(0, "t"), row(10, "u")], DUR)), [])

    def test_imported_rows_are_left_out(self):
        self.assertEqual(list(dd.chains([row(0), row(10, context="")], DUR)), [])


class TestListens(unittest.TestCase):
    def test_nothing_in_the_export_is_one_listen(self):
        self.assertEqual(dd.listens([], 200), (1, "not_in_export"))

    def test_one_short_segment_is_one_listen(self):
        self.assertEqual(dd.listens([(1000, 30000)], 200), (1, "one_listen"))

    def test_pieces_with_a_short_pause_are_one_listen(self):
        # 140s, paused 60s, then the last 60s.
        segments = [(1000, 140000), (1000 + 60 + 60, 60000)]
        self.assertEqual(dd.listens(segments, 200), (1, "one_listen_in_pieces"))

    def test_a_full_play_and_a_short_tail_is_one_listen(self):
        segments = [(1000, 200000), (1020, 20000)]
        self.assertEqual(dd.listens(segments, 200)[0], 1)

    def test_the_track_heard_twice_is_a_repeat(self):
        segments = [(1000, 200000), (1200, 200000)]
        self.assertEqual(dd.listens(segments, 200), (2, "repeat"))

    def test_heard_three_times_is_three_listens(self):
        segments = [(1000, 200000), (1200, 200000), (1400, 200000)]
        self.assertEqual(dd.listens(segments, 200), (3, "repeat"))

    def test_a_pause_over_the_limit_makes_separate_sittings(self):
        pause = dd.BIG_PAUSE_SECONDS + 1
        segments = [(1000, 100000), (1000 + pause + 100, 100000)]
        self.assertEqual(dd.listens(segments, 200), (2, "separate_sittings"))

    def test_a_pause_of_exactly_the_limit_is_still_one_sitting(self):
        pause = dd.BIG_PAUSE_SECONDS
        segments = [(1000, 100000), (1000 + pause + 100, 100000)]
        self.assertEqual(dd.listens(segments, 200)[0], 1)

    def test_segment_order_does_not_matter(self):
        segments = [(1200, 200000), (1000, 200000)]
        self.assertEqual(dd.listens(segments, 200), (2, "repeat"))


class TestPlan(unittest.TestCase):
    def test_removes_the_later_rows_and_points_at_the_kept_one(self):
        removals, tally = dd.plan([row(0), row(40), row(80)], DUR,
                                  lambda *_: [(60, 200000)])
        self.assertEqual([r["id"] for r in removals], ["40", "80"])
        self.assertTrue(all(r["kept_id"] == "0" for r in removals))
        self.assertEqual(tally["one_listen"], 2)

    def test_keeps_as_many_rows_as_listens(self):
        removals, _ = dd.plan([row(0), row(150), row(170)], DUR,
                              lambda *_: [(0, 200000), (150, 200000)])
        self.assertEqual([r["id"] for r in removals], ["170"])
        self.assertEqual(removals[0]["kept_id"], "150")

    def test_removed_rows_keep_every_original_field(self):
        removals, _ = dd.plan([row(0), row(40)], DUR, lambda *_: [])
        original = row(40)
        self.assertEqual({k: removals[0][k] for k in original}, original)
        self.assertEqual(removals[0]["reason"], "not_in_export")

    def test_a_rerun_removes_nothing_new(self):
        # Judged alone, the two rows left would see only the first two
        # segments: one listen. Judged with the removed rows back in their
        # chain, the decision is the same as the first time.
        rows = [row(0), row(150), row(170), row(320)]
        segments = [(0, 200000), (150, 200000), (320, 200000)]
        seg = lambda t, a, b: [s for s in segments if a <= s[0] <= b]
        first, _ = dd.plan(rows, DUR, seg)
        left = [r for r in rows if r["id"] not in {x["id"] for x in first}]
        second, _ = dd.plan(left, DUR, seg, removed=first)
        self.assertEqual([r["id"] for r in first], ["320"])
        self.assertEqual(second, [])

    def test_looks_for_segments_around_the_whole_chain(self):
        seen = []
        dd.plan([row(1000), row(1050)], DUR,
                lambda t, a, b: seen.append((t, a, b)) or [])
        self.assertEqual(seen, [("t", 1000 - 200 - dd.SEGMENT_MARGIN_SECONDS,
                                 1050 + dd.SEGMENT_MARGIN_SECONDS)])


if __name__ == "__main__":
    unittest.main()
