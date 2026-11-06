"""Names of Spotify's own playlists (37i9dQZ...), recorded as they are seen.

The Web API will not return these playlists, which is why Playlist.excludeStore
skips them, but the public oEmbed endpoint still reports their title with no
credentials. Measured 2026-11-06: 71 of the 75 IDs in the history resolved;
the other 4 return 404, gone from Spotify.

Their names drift — daylist retitles itself several times a day, and Spotify
removes expired mixes — so a lookup made later cannot say what a playlist was
called when it was played. The file is therefore a log, not a table: a row is
appended whenever an ID is new or its name differs from the last one recorded.
Join a play to the row with the same id and the latest fetched_at at or before
it (or simply the nearest one; the collector fetches within the hour).
"""
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import ReadWrite as rw

storing_path = "spotify_playlists.csv"
FIELDS = ["id", "name", "fetched_at"]
OEMBED = "https://open.spotify.com/oembed?url="


def fetchName(playlist_id, timeout=10):
    """Current title of a playlist, or None if Spotify no longer has it."""
    url = OEMBED + urllib.parse.quote(f"https://open.spotify.com/playlist/{playlist_id}", safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response).get("title") or None
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def latestNames():
    """{id: most recently recorded name}."""
    full_path = os.path.join(rw.DATA, storing_path)
    if not os.path.exists(full_path):
        return {}
    with open(full_path, mode='r', newline='', encoding='utf-8') as file:
        rows = sorted(csv.DictReader(file), key=lambda row: int(row["fetched_at"]))
    return {row["id"]: row["name"] for row in rows}


def record(playlist_ids, fetch=fetchName, now=None):
    """Look up each ID and append the ones whose name is new. Returns those rows.

    Never raises: a name is a nicety, and a network hiccup here must not cost
    the plays the same run is collecting.
    """
    known = latestNames()
    fetched_at = int(now if now is not None else time.time())
    new_rows = []
    for playlist_id in sorted(set(playlist_ids)):
        try:
            name = fetch(playlist_id)
        except Exception as error:
            print(f"Could not look up playlist {playlist_id}: {error}")
            continue
        if name is not None and known.get(playlist_id) != name:
            new_rows.append({"id": playlist_id, "name": name, "fetched_at": fetched_at})

    if new_rows:
        full_path = os.path.join(rw.DATA, storing_path)
        file_exists = os.path.exists(full_path)
        with open(full_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerows(new_rows)
    return new_rows
