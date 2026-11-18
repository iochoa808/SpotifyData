# SpotifyData

A personal listening-history archive. A GitHub Actions job polls Spotify's
recently-played endpoint every 30 minutes and commits what it finds, so the
history accumulates in git instead of expiring. The interval comes from an
external timer (cron-job.org); GitHub's own scheduler is kept only as a backup,
because on its own it is too irregular to rely on.

It exists because the API remembers almost nothing: **Spotify retains only
about 50 recent plays**. A heavy listening session fills that in two to three
hours, and anything not collected by then is gone for good. That single fact
drives most of the design decisions below.

As of 18 November 2026: **57,203 plays** spanning **2024-12-14 to
2026-11-18**.

## How it works

```
Spotify API
     │  every 30 min, .github/workflows/python-script.yml
     ▼
 collector  ──writes──▶  data/*.csv      append-only · committed · system of record
                              │
                              │  python src/database.py build   (~4s)
                              ▼
                         spotify.db      normalised · gitignored · derived
                              │
                              ▼
                         analysis
```

The CSVs are the system of record, not the database. They are append-only, they
diff readably, and — the deciding reason — **git can merge them**. When two
sides collect independently, a text conflict keeps both sides' rows; a binary
`.db` conflict keeps one and discards the other. That is not hypothetical: it
happened during the 2026 recovery, and 28 plays survived only because the
canonical store was text.

The database is a derived read model, rebuilt from scratch each time. Nothing in
the collection path reads it, so a mistake there cannot cost a play.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp src/.env.example src/.env        # then fill in the three values
.venv/bin/python src/auth_catch.py  # mint a REFRESH_TOKEN (opens a consent link)
.venv/bin/python src/main.py        # collect
```

`src/auth_catch.py` runs a throwaway server on port 8888 to catch Spotify's
OAuth redirect, so there is nothing to copy by hand. The redirect URI it uses
must be registered **verbatim** in the
[app dashboard](https://developer.spotify.com/dashboard); Spotify rejects
`localhost`, so use `http://127.0.0.1:8888/callback`.

### Secrets

| Name | Where | From |
|---|---|---|
| `CLIENT_ID` | `src/.env` and repo secrets | app dashboard |
| `CLIENT_SECRET` | `src/.env` and repo secrets | app dashboard |
| `REFRESH_TOKEN` | `src/.env` and repo secrets | `src/auth_catch.py` |

`src/.env` is gitignored. A refresh token does not expire on a timer but **is
revoked by a password change or by removing app access** at
`spotify.com/account/apps` — which is exactly what broke this project for 98
days in 2026.

### Database and tests

```bash
.venv/bin/python src/database.py build     # rebuild spotify.db from the CSVs
.venv/bin/python src/database.py verify    # foreign keys + row counts vs CSVs
.venv/bin/python src/database.py stats
python3 -m unittest discover -s tests      # 78 tests, stdlib only, no credentials
```

## Data

### `data/*.csv` — the system of record

| File | Key | Notes |
|---|---|---|
| `recently_played.csv` | `id` — UTC epoch seconds | one row per play |
| `songs.csv` | `id` | `artists_id` is a stringified list |
| `albums.csv` | `id` | `tracks`, `images` stringified lists |
| `artists.csv` | `id` | `genres`, `images` stringified lists |
| `playlists.csv` | `id` | Spotify's own playlists (`37i9dQZ…`) are not stored; the API refuses them |
| `spotify_playlists.csv` | `id` + `fetched_at` | names of Spotify's own playlists, a log — see below |

File order is append order, not sorted — the last line is not reliably the
newest play. Use `MAX(played_at)`.

### `spotify.db` — the derived model

Lists become real tables: `song_artists`, `album_artists`, `album_tracks`,
`artist_genres`, `artist_images`, `album_images`, `playlist_images`. Two views,
`play_artists` and `plays_detail`, cover most questions without writing joins.

**Names of Spotify's own playlists.** The Web API refuses playlists like
daylist, Discover Weekly and the mixes, yet they are the context of 28% of all
plays. Their titles come from Spotify's public oEmbed endpoint
instead (`src/playlist_names.py`), and because they drift — daylist retitles
itself several times a day — `spotify_playlists.csv` is a log: a row is added
whenever an ID is new or its name has changed, never rewritten. It loads into
`spotify_playlist_names`, and `plays_detail.playlist_name` gives every playlist
play a name: the stored playlist's own, otherwise the logged name nearest the
play. A lookup failure never costs a play; the name is simply missing.

Three relations carry **no foreign key**, each for a measured reason documented
in `src/database.py`:

- `album_tracks.track_id` — albums list every track; only played tracks are
  stored, so most point at tracks we don't have.
- `album_artists.artist_id` — some albums credit artists never fetched.
- `plays.context_id` — polymorphic, and most playlist contexts are editorial
  playlists skipped by design.

`release_date` is `TEXT` because Spotify returns three precisions (`2020`,
`2020-04`, `2020-04-10`); a `DATE` column would invent January 1st.

### Provenance: `plays_detail.source`

| Source | Plays | Has context | Has popularity |
|---|---|---|---|
| `api` | 52,012 | yes | yes |
| `import` | 5,191 | no | no |

Plays recovered from a bulk export have no playlist context and no popularity
at play time, so both columns are empty rather than guessed. **Any analysis
that uses context or popularity should filter on `source`** instead of
averaging the two regimes together.

## Backfilling from a Spotify export

`src/import_history.py` imports plays the collector never saw, from a GDPR
**"Extended streaming history"** export (request it under Privacy Settings; it
takes a few weeks and is *not* the fast basic export, which lacks track IDs).

```bash
.venv/bin/python src/import_history.py --zip my_spotify_data.zip \
    --since 2026-07-20 --until 2026-10-27 --dry-run
```

Rules it follows, all for the sake of keeping imported plays comparable to
collected ones:

- Plays under 30s are dropped; the API only ever reported plays past that.
- Deduplication allows 15 seconds of drift. The export's `ts` and the API's
  `played_at` were verified to mean the same thing, agreeing exactly for most
  of 50,212 cross-checked plays and within 3 seconds for the rest.
- A timestamp already owned by a different track is skipped and reported, never
  nudged — `played_at` is the primary key, and moving one invents a play time.

> **The export contains an IP address, device platform and country for every
> play, and this repository is public.** The zip is gitignored and only the
> timestamp, track id, track name and `ms_played` are ever read from it. Keep it
> that way.

### Not done: nine years of pre-2024 history

The same export covers **2015-06 onward — 186,490 importable plays over 2,484
days**, roughly 3.3× the current dataset. It is deliberately **not** imported.

```bash
# available, not run:
.venv/bin/python src/import_history.py --zip my_spotify_data.zip \
    --since 2015-01-01 --until 2024-12-14
```

The reasons to think before running it:

- **It changes what the dataset is**, rather than repairing it. Nine years of
  bulk-export history would sit beside two years of purpose-built collection at
  a different fidelity.
- **None of it has playlist context.** Coverage would fall from **91% of plays
  to 21%** (playlist context specifically, from 69% to 16%), weakening every
  "where do I listen from" question — the most distinctive thing this archive
  can answer.
- **No popularity at play time**, so trend analysis over that span is unavailable.
- It needs **23,419 track lookups** — roughly 469 track requests plus albums and
  artists, so a few thousand API calls and some tens of minutes.

The repaired 2026 outage was different: that was 90 days of genuinely missing
rows inside the collection period, so filling it restored the record rather than
redefining it.

A smaller, clearly worthwhile version of this remains open. Two gaps inside the
collection period are still empty, and a fresh export would close both:

- **23 October 21:15 – 26 October 13:01 UTC** — after the export was generated,
  before the collector came back.
- **13 November 23:37 – 16 November 15:21 UTC** — the November outage (see
  *Outages* below). Some of this window may genuinely have no listening; the
  plays lost are those from about 15 November afternoon onward.

## Operations

Two workflows:

- **`python-script.yml`** ("Collect Listening History") — collection every 30
  minutes, fired by cron-job.org with GitHub's own schedule as a backup. Runs
  the tests, collects, then commits and pushes with a concurrency guard and
  rebase-and-retry. **Raises a GitHub issue on failure**, which is the lesson
  of the 2026 outage: the broken token cost one click to fix, while the 98 days
  of unnoticed silence cost history that cannot be recovered.
- **`publish-database.yml`** — weekly, and manually dispatchable. Builds and
  verifies the database and uploads it as an artifact. Kept off the collection
  path so collection stays a seven-second job.

Scheduled workflows are disabled by GitHub after 60 days without repository
activity. Successful runs commit, and commits reset that timer, so this only
becomes a problem once collection is already broken.

**Reading the Actions list.** Each run is titled by what triggered it —
`Collect plays · cron-job.org`, `· GitHub schedule` or `· manual`. The title is
fixed before the run starts, so the number of plays collected is shown instead
on the run's summary page ("12 new plays collected") and in its commit message:
`Collect 12 plays`, or `Update metadata, no new plays` when only a song,
album or playlist name changed. Runs with nothing new make no commit. Commits
before 18 November 2026 are all titled `Updated CSV files`.

### The schedule is not reliable, and that costs plays

GitHub's `schedule` event is best-effort, and how often it fires bears little
relation to what the cron asks for. Measured on this repository: a 2-hourly
entry fired 8.4 times a day in August 2026, typically 40 minutes late; a single
hourly entry from 27 October to 2 November managed only 4–5 a day; and on
2 November it went quiet for **15.9 hours** before resuming unprompted, with the
workflow active and no GitHub incident.

That matters because the gap between runs is the only protection there is.
Against this account's own history:

| Gap between runs | Busiest window | vs the ~50-play ceiling |
|---|---|---|
| 2 hours | 47 plays | safe, barely |
| **3 hours** | **64 plays** | **loses ~14** |
| 5 hours | 101 plays | loses ~51 |

This is not theoretical: **65 commits in the history added exactly 45–60 plays**,
which is the signature of a full window with older plays already scrolled out.

Four cron entries across the hour improve the odds and nothing more. Measured
over 7–18 November 2026 against the single 2-hourly entry in August, they fired
more runs (14.4 a day against 8.4) but in bursts of 2–4 within half an hour,
so the gap that matters — between bursts — *grew*, from a median of 2.2 hours
to 3.9. After a stall the scheduler fires the overdue entries back to back; the
extra entries only add runs that find nothing new. A dependable interval has to
come from outside Actions, which is what the external scheduler below provides.
The four entries are still in the workflow, now only as a backup for it.

### External scheduler

The workflow accepts a `repository_dispatch` event of type `collect`, so any
external timer can fire it:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/iochoa808/SpotifyData/dispatches \
  -d '{"event_type":"collect"}'
```

`scripts/trigger-collection.sh` wraps that with useful error messages — run it
once locally to confirm the token works before handing it to a scheduler:

```bash
GITHUB_PAT=github_pat_... ./scripts/trigger-collection.sh
```

A success is **HTTP 204** with no body.

**The token.** Create a *fine-grained* token at
[Settings → Personal access tokens](https://github.com/settings/personal-access-tokens/new):

| Setting | Value |
|---|---|
| Repository access | Only select repositories → `SpotifyData` |
| Permissions | Repository permissions → **Contents: Read and write** |
| Expiration | Set one, and diarise the renewal |

Contents write is the only permission the dispatches endpoint needs. The token
can push to this repository, so treat it as a password: put it only in the
scheduler's secret field, never in the repo, and never in a commit. An expired
token fails closed — collection falls back to GitHub's unreliable schedule
rather than breaking — so renewal is the thing to watch.

Run the script from an ordinary terminal, with a leading space so the token
stays out of shell history — not through an AI assistant or anything that logs
the command.

**The scheduler: cron-job.org.** Live since 18 November 2026; the first
dispatched run was at 16:45 UTC. The cronjob at <https://cron-job.org> is set
up as:

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/iochoa808/SpotifyData/dispatches` |
| Schedule | Every 30 minutes |
| Request method | `POST` |
| Header | `Accept: application/vnd.github+json` |
| Header | `Authorization: Bearer github_pat_...` (the token above) |
| Header | `X-GitHub-Api-Version: 2022-11-28` |
| Header | `Content-Type: application/json` |
| Request body | `{"event_type":"collect"}` |
| Notifications | On failed execution — success is **HTTP 204** |

Its runs show in Actions as `Collect plays · cron-job.org`, with event
`repository_dispatch`. Thirty minutes is well inside the two-hour limit from the
table above. Runs that overlap queue rather than cancel (the concurrency group),
a run with nothing new is a no-op, and Actions minutes are free on a public
repository, so the interval costs nothing.

**When something goes wrong:**

| Symptom | Cause | Fix |
|---|---|---|
| cron-job.org reports 401 or 403 | Token expired or revoked | Make a new token as above, test it with the script, paste it into the `Authorization` header |
| cron-job.org reports 404 | Repo renamed, or token lost access to it | Fix the URL, or the token's repository access |
| cron-job.org reports 422 | No `collect` dispatch trigger on `main` | Restore `repository_dispatch: types: [collect]` in the workflow |
| 204, but the run fails | Collector problem, not the trigger | The `collector-down` issue links the failing run |
| No `cron-job.org` runs at all | Job disabled — cron-job.org pauses jobs after repeated failures | Re-enable it in the cron-job.org dashboard |

GitHub's own `schedule` stays in the workflow as a backup, so a broken trigger
slows collection down rather than stopping it.

Any other service that can POST on a timer works the same way: the URL, method
`POST`, the headers and the body above, at an interval of 30 minutes or better.

A local timer is the alternative if this machine is usually on, and needs no
token at all — it can run `src/main.py` directly and push. Both sources can
collect at once safely: it has happened twice, and git reconciled both without
duplicates, because `played_at` is the primary key and the CSVs merge as text.

### Outages

| When (UTC) | Cause | Cost | Fixed by |
|---|---|---|---|
| 2026-07-20 → 2026-10-27 | Spotify revoked `REFRESH_TOKEN`; every run failed for 98 days unnoticed, until GitHub disabled the schedule | ~3 months, mostly backfilled from an export | A new token, and the `collector-down` alarm issue |
| 2026-11-15 16:56 → 2026-11-16 20:16 | A play whose playlist context came as the legacy `spotify:user:<name>:playlist:<id>` URI. The ID was read as segment 2 — the username — which spotipy rejected, crashing before anything was stored; every run then hit the same play until it left the 50-play window | Plays from ~15 Nov afternoon to 16 Nov 15:21 | `utils.contextId()` handles both URI shapes, and a playlist that cannot be fetched is logged and skipped instead of aborting the run |

The pattern in both: a failure that repeats on every run. Anything that stops
a run before plays are stored also stops the cursor from moving, so the next run
meets the same problem — keep lookups that can fail on one item from failing the
whole run.

## Layout

```
src/main.py              entry point: collect and store recent plays
src/Classes.py           Song, Album, Artist, Playlist, PlayedSong
src/Spotify.py           authenticated client
src/ReadWrite.py         CSV read/write with a cached key set
src/utils.py             timestamps, batching, nested lookups, context IDs
src/playlist_names.py    names of Spotify's own playlists, via oEmbed
src/database.py          schema and builder for the derived database
src/auth_catch.py        one-shot refresh-token minter
src/import_history.py    backfill from a GDPR export
src/migrate_data0.py     one-shot import of the original 2024 schema
scripts/trigger-collection.sh  fire the collector by hand, or test a token
.github/workflows/       collection and the weekly database build
tests/                   78 stdlib-only tests
data/                    the CSVs — system of record
data0/                   the original schema, fully migrated into data/
```

Original reference:
<https://github.com/AzeemIdrisi/TweetifyMusic/blob/main/tweetifymusic.py>
