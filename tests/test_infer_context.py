"""Tests for inferring imported plays' context from their neighbours.

    python -m unittest discover -s tests -v

Plays are (played_at, track_id, context_type, context_id); an empty
context_type is an imported play.
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import infer_context as ic  # noqa: E402

PL = "6bYdhADwAwPJNXrc2i3nSY"          # one of the account's own playlists
DAYLIST = "37i9dQZF1EYkqdzj48dyYq"     # Spotify's own: unreadable


def api(ts, track, ctype="playlist", cid=PL):
    return (ts, track, ctype, cid)


def imported(ts, track):
    return (ts, track, "", "")


def membership(members):
    return lambda playlist_id: members.get(playlist_id)


SONGS = {"on": ("alb1", ["art1"]), "off": ("alb2", ["art2"])}
ALBUMS = {"alb1": {"on"}}


class TestCandidates(unittest.TestCase):
    def test_bridges_a_play_between_two_of_one_context(self):
        found, _ = ic.candidates([api(0, "a"), imported(200, "x"), api(400, "b")])
        self.assertEqual(found, [(imported(200, "x"), "playlist", PL)])

    def test_bridges_every_play_of_a_run(self):
        plays = [api(0, "a"), imported(200, "x"), imported(400, "y"), api(600, "b")]
        found, _ = ic.candidates(plays)
        self.assertEqual([p[0][1] for p in found], ["x", "y"])

    def test_input_order_does_not_matter(self):
        found, _ = ic.candidates([api(400, "b"), imported(200, "x"), api(0, "a")])
        self.assertEqual(len(found), 1)

    def test_different_neighbours_bridge_nothing(self):
        plays = [api(0, "a"), imported(200, "x"), api(400, "b", "album", "alb1")]
        found, skipped = ic.candidates(plays)
        self.assertEqual(found, [])
        self.assertEqual(skipped["neighbours_differ"], 1)

    def test_same_type_but_different_id_is_different(self):
        plays = [api(0, "a"), imported(200, "x"), api(400, "b", cid="other")]
        self.assertEqual(ic.candidates(plays)[0], [])

    def test_a_long_pause_anywhere_in_the_run_breaks_it(self):
        gap = ic.MAX_GAP_SECONDS + 1
        plays = [api(0, "a"), imported(200, "x"), imported(200 + gap, "y"),
                 api(400 + gap, "b")]
        found, skipped = ic.candidates(plays)
        self.assertEqual(found, [])
        self.assertEqual(skipped["session_break"], 2)

    def test_a_pause_of_exactly_the_limit_is_allowed(self):
        gap = ic.MAX_GAP_SECONDS
        plays = [api(0, "a"), imported(gap, "x"), api(2 * gap, "b")]
        self.assertEqual(len(ic.candidates(plays)[0]), 1)

    def test_plays_at_either_end_have_no_bridge(self):
        found, skipped = ic.candidates([imported(0, "x"), api(200, "a"),
                                        imported(400, "y")])
        self.assertEqual(found, [])
        self.assertEqual(skipped["no_neighbour"], 2)


class TestCheck(unittest.TestCase):
    def check(self, track, ctype, cid, members=None, ts=1000):
        return ic.check((ts, track), ctype, cid, SONGS, ALBUMS,
                        membership(members or {}))

    def test_album_by_the_tracks_own_album_or_the_albums_list(self):
        self.assertEqual(self.check("on", "album", "alb1"), ("on_album", True))
        songs_elsewhere = {"on": ("single", ["art1"])}
        self.assertEqual(ic.check((0, "on"), "album", "alb1", songs_elsewhere,
                                  ALBUMS, membership({})), ("on_album", True))
        self.assertEqual(self.check("off", "album", "alb1"), ("not_on_album", False))

    def test_artist(self):
        self.assertEqual(self.check("on", "artist", "art1"), ("by_artist", True))
        self.assertEqual(self.check("off", "artist", "art1"), ("not_by_artist", False))

    def test_playlist_member_added_before_the_play(self):
        self.assertEqual(self.check("on", "playlist", PL, {PL: {"on": 500}}),
                         ("in_playlist", True))

    def test_playlist_member_added_after_the_play(self):
        self.assertEqual(self.check("on", "playlist", PL, {PL: {"on": 5000}}),
                         ("added_after_play", False))

    def test_playlist_member_without_an_added_date(self):
        self.assertEqual(self.check("on", "playlist", PL, {PL: {"on": None}}),
                         ("in_playlist_undated", True))

    def test_not_in_the_playlist(self):
        self.assertEqual(self.check("off", "playlist", PL, {PL: {"on": 500}}),
                         ("not_in_playlist", False))

    def test_unreadable_playlist(self):
        self.assertEqual(self.check("on", "playlist", PL, {}),
                         ("playlist_unreadable", False))

    def test_spotify_playlists_and_liked_songs_are_unverifiable(self):
        for cid in (DAYLIST, ic.LIKED_SONGS):
            with self.subTest(cid=cid):
                self.assertEqual(self.check("on", "playlist", cid),
                                 (ic.UNVERIFIABLE, False))


class TestInfer(unittest.TestCase):
    PLAYS = [api(0, "a"), imported(200, "on"), imported(400, "off"), api(600, "b")]
    MEMBERS = staticmethod(membership({PL: {"on": 100}}))

    def test_keeps_unconfirmed_rows_with_their_evidence(self):
        rows, tally = ic.infer(self.PLAYS, SONGS, ALBUMS, self.MEMBERS)
        self.assertEqual([(r["id"], r["evidence"]) for r in rows],
                         [(200, "in_playlist"), (400, "not_in_playlist")])
        self.assertTrue(all(r["context_id"] == PL for r in rows))

    def test_strict_keeps_only_confirmed_rows(self):
        rows, tally = ic.infer(self.PLAYS, SONGS, ALBUMS, self.MEMBERS, strict=True)
        self.assertEqual([r["id"] for r in rows], [200])
        self.assertEqual(tally["dropped_not_in_playlist"], 1)

    def test_skips_plays_already_inferred(self):
        rows, tally = ic.infer(self.PLAYS, SONGS, ALBUMS, self.MEMBERS, done={200})
        self.assertEqual([r["id"] for r in rows], [400])
        self.assertEqual(tally["already_inferred"], 1)

    def test_collected_plays_are_never_touched(self):
        rows, _ = ic.infer(self.PLAYS, SONGS, ALBUMS, self.MEMBERS)
        self.assertNotIn(0, [r["id"] for r in rows])
        self.assertNotIn(600, [r["id"] for r in rows])


class TestAppend(unittest.TestCase):
    ROW = {"id": 2, "context_type": "album", "context_id": "a", "evidence": "on_album"}

    def test_writes_a_header_for_a_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inferred_contexts.csv"
            ic.append([self.ROW], path)
            self.assertEqual(path.read_text(),
                             "id,context_type,context_id,evidence\n2,album,a,on_album\n")

    def test_appends_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inferred_contexts.csv"
            path.write_bytes(b"id,context_type,context_id,evidence\r\n1,x,y,z")
            ic.append([self.ROW], path)
            self.assertEqual(path.read_bytes(),
                             b"id,context_type,context_id,evidence\r\n1,x,y,z\n"
                             b"2,album,a,on_album\n")


if __name__ == "__main__":
    unittest.main()
