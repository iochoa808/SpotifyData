"""Infer the missing context of imported plays from the plays around them.

    python src/infer_context.py --dry-run     # report, write nothing
    python src/infer_context.py               # append to data/inferred_contexts.csv

Plays backfilled from the GDPR export have no context: the export does not say
which playlist, album or artist a play came from. Most of them, though, sit in
the middle of a listening session the collector did see. When the collected
plays on both sides of an imported one (or of a run of imported ones) share a
context, the imported plays almost certainly came from it too.

A play gets a context when:

  - the nearest archived play before it and the nearest after it both have
    an observed context, and it is the same one;
  - the session is unbroken: no two consecutive plays from the earlier
    neighbour to the later one are more than MAX_GAP_SECONDS apart.

How good that is was measured rather than assumed, by hiding each collected
play that sits between two same-context neighbours and asking the rule for it
(2026-11-20, ~41,000 plays): it named the context the API had recorded 99.5%
of the time.

Whether the track belongs to the context is checked too, and recorded as the
row's evidence, but by default it does not veto the inference. The same
experiment showed why: the API's context is where the session was started, not
where the track lives. Autoplay after an album keeps the album as the context,
and a track since removed from a playlist was still played from it. Of the
collected plays, only 37% are on their context album's track list and 81% are
in their context playlist today, so requiring membership would reject far more
right answers than wrong ones. Imported plays pass at the same rates (31%,
84%), which is the evidence that they come from the same kind of session.

  evidence             meaning
  on_album             the track is on the context album
  by_artist            the track credits the context artist
  in_playlist          in the playlist today, added before the play
  in_playlist_undated  in the playlist today, no added date (old playlists)
  not_on_album, not_by_artist, not_in_playlist, added_after_play,
  playlist_unreadable  the check failed or could not be made
  unverifiable         Spotify's own playlists and Liked Songs, which this
                       app's access cannot read

--strict keeps only rows whose check passed.

Inferences go to data/inferred_contexts.csv, never into recently_played.csv,
which records only what the API observed. The file is append-only like the
rest: playlist membership is read from the API as it is today, and a track
removed from a playlist later would make a re-run reach a different answer, so
earlier conclusions are kept rather than recomputed.
"""
from pathlib import Path
import argparse
import ast
import csv
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
OUTPUT = "inferred_contexts.csv"
HEADER = ["id", "context_type", "context_id", "evidence"]

# Longest pause allowed between consecutive plays inside a bridged run. A gap
# this long means the session may have ended and another begun in between.
MAX_GAP_SECONDS = 30 * 60

LIKED_SONGS = "0000000000000000000000"
SPOTIFY_OWNED = "37i9dQZ"

CONFIRMED = {"on_album", "by_artist", "in_playlist", "in_playlist_undated"}
UNVERIFIABLE = "unverifiable"


def unverifiable(context_type, context_id):
    return context_type == "playlist" and (
        context_id == LIKED_SONGS or context_id.startswith(SPOTIFY_OWNED))


def candidates(plays, max_gap=MAX_GAP_SECONDS):
    """Imported plays bridged by two collected plays of one context.

    plays: (played_at, track_id, context_type, context_id), any order; an empty
    context_type marks an imported play. Yields (play, context_type, context_id).
    Also returns counts of why the other imported plays were not bridged.
    """
    plays = sorted(plays)
    skipped = {"no_neighbour": 0, "neighbours_differ": 0, "session_break": 0}
    found = []
    i = 0
    while i < len(plays):
        if plays[i][2]:
            i += 1
            continue
        j = i
        while j < len(plays) and not plays[j][2]:
            j += 1
        run = plays[i:j]
        before = plays[i - 1] if i > 0 else None
        after = plays[j] if j < len(plays) else None
        i = j
        if before is None or after is None:
            skipped["no_neighbour"] += len(run)
        elif (before[2], before[3]) != (after[2], after[3]):
            skipped["neighbours_differ"] += len(run)
        else:
            span = [before, *run, after]
            if any(b[0] - a[0] > max_gap for a, b in zip(span, span[1:])):
                skipped["session_break"] += len(run)
            else:
                found.extend((p, before[2], before[3]) for p in run)
    return found, skipped


def check(play, context_type, context_id, songs, album_tracks, playlist_added):
    """Evidence that the track fits the context, or a reason it does not.

    songs: track_id -> (album_id, [artist_id, ...]).
    album_tracks: album_id -> set of track ids.
    playlist_added: callable(playlist_id) -> {track_id: earliest added_at epoch
    or None}, or None when the playlist cannot be read.
    Returns (evidence, confirmed).
    """
    played_at, track_id = play[0], play[1]
    if unverifiable(context_type, context_id):
        return UNVERIFIABLE, False
    if context_type == "album":
        on = (songs.get(track_id, (None, []))[0] == context_id
              or track_id in album_tracks.get(context_id, ()))
        return ("on_album", True) if on else ("not_on_album", False)
    if context_type == "artist":
        artists = songs.get(track_id, (None, []))[1]
        return ("by_artist", True) if context_id in artists else ("not_by_artist", False)
    if context_type == "playlist":
        members = playlist_added(context_id)
        if members is None:
            return "playlist_unreadable", False
        if track_id not in members:
            return "not_in_playlist", False
        added = members[track_id]
        if added is None:
            return "in_playlist_undated", True
        return ("in_playlist", True) if added <= played_at else ("added_after_play", False)
    return "unknown_context_type", False


def infer(plays, songs, album_tracks, playlist_added, done=(), strict=False):
    """The rows to append, and a tally of every outcome."""
    found, tally = candidates(plays)
    rows = []
    for play, context_type, context_id in found:
        if play[0] in done:
            tally["already_inferred"] = tally.get("already_inferred", 0) + 1
            continue
        evidence, confirmed = check(play, context_type, context_id,
                                    songs, album_tracks, playlist_added)
        kept = confirmed or not strict
        key = evidence if kept else f"dropped_{evidence}"
        tally[key] = tally.get(key, 0) + 1
        if kept:
            rows.append({"id": play[0], "context_type": context_type,
                         "context_id": context_id, "evidence": evidence})
    return rows, tally


def api_membership():
    """playlist_added for infer(), reading playlists from the API once each."""
    import utils
    from Spotify import sp
    cache = {}

    def lookup(playlist_id):
        if playlist_id not in cache:
            try:
                members = {}
                page = sp.playlist_items(
                    playlist_id, limit=100,
                    fields="next,items(added_at,track(id))")
                while page:
                    for item in page["items"]:
                        track = item.get("track") or {}
                        if not track.get("id"):
                            continue
                        added = (utils.toTimestamp(item["added_at"])
                                 if item.get("added_at") else None)
                        previous = members.get(track["id"], added)
                        members[track["id"]] = (
                            None if added is None or previous is None
                            else min(added, previous))
                    page = sp.next(page) if page.get("next") else None
                cache[playlist_id] = members
            except Exception as error:  # unreadable: deleted, private, refused
                print(f"  cannot read playlist {playlist_id}: {error}")
                cache[playlist_id] = None
        return cache[playlist_id]

    return lookup


def read(name):
    path = DATA / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load():
    plays = [(int(r["id"]), r["track_id"], r["context_type"], r["context_id"])
             for r in read("recently_played.csv")]
    songs = {r["id"]: (r["album_id"], ast.literal_eval(r["artists_id"] or "[]"))
             for r in read("songs.csv")}
    album_tracks = {r["id"]: set(ast.literal_eval(r["tracks"] or "[]"))
                    for r in read("albums.csv")}
    done = {int(r["id"]) for r in read(OUTPUT)}
    return plays, songs, album_tracks, done


def append(rows, path=None):
    """Append rows, writing the header if the file is new."""
    path = path or DATA / OUTPUT
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        with open(path, "rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) != b"\n"
    with open(path, "a", newline="", encoding="utf-8") as handle:
        if not new and needs_newline:
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=HEADER, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["id"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="report without writing (still reads playlists)")
    parser.add_argument("--strict", action="store_true",
                        help="keep only plays whose track is confirmed in the context")
    args = parser.parse_args(argv)

    plays, songs, album_tracks, done = load()
    imported = sum(1 for p in plays if not p[2])
    print(f"Imported plays without context: {imported:,}")
    rows, tally = infer(plays, songs, album_tracks, api_membership(), done,
                        args.strict)
    width = max(map(len, tally)) + 2
    for key, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {key:<{width}}{n:>7,}")
    confirmed = sum(r["evidence"] in CONFIRMED for r in rows)
    unverifiable = sum(r["evidence"] == UNVERIFIABLE for r in rows)
    print(f"\nInferred: {len(rows):,} ({confirmed:,} confirmed in context, "
          f"{unverifiable:,} unverifiable, "
          f"{len(rows) - confirmed - unverifiable:,} not confirmed)")
    if args.dry_run:
        print("Dry run; nothing written.")
    elif rows:
        append(rows)
        print(f"Appended to data/{OUTPUT}. Rebuild: python src/database.py build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
