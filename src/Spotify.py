"""Authenticated Spotify client shared by the rest of src/.

Unattended runs can't open a browser, so auth is the Authorization Code flow
driven by a long-lived refresh token held in the environment. Mint that token
once with `python src/auth_catch.py`; after that every run just exchanges it
for a short-lived access token.

A rejected refresh token is what stopped this pipeline on 2026-07-20: the runs
kept firing for 60 days, each one crashing here, until GitHub disabled the
schedule for inactivity. The failure is loud now, and the workflow raises an
issue when it happens.
"""
from pathlib import Path
import os
import sys

import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from dotenv import load_dotenv

SCOPE = "user-read-recently-played"

# Spotify rejects `localhost` redirect URIs; it wants an explicit loopback IP.
# This has to match the URI registered in the app dashboard exactly.
REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Load src/.env by absolute path. A bare load_dotenv() only searches upward from
# the working directory, so it silently found nothing when main.py was run from
# the repository root.
load_dotenv(Path(__file__).with_name(".env"))


def require_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(
            f"[auth] {name} is not set.\n"
            f"       Locally: add it to src/.env (see src/.env.example).\n"
            f"       In CI:   add it under Settings > Secrets and variables > Actions."
        )
    return value


def report_rotated_token(new_token):
    """Surface a refresh token that Spotify replaced mid-flight.

    Spotify usually returns the same refresh token, but when it issues a new one
    the old one can stop working — which strands an unattended pipeline exactly
    the way this one was stranded. The run is allowed to finish (the access token
    in hand is valid), but the new token is made impossible to miss.
    """
    message = (
        "Spotify issued a NEW refresh token. The REFRESH_TOKEN currently in use "
        "may stop working on a future run. Update the secret to:\n"
        f"    {new_token}"
    )
    print(f"[auth] WARNING: {message}", file=sys.stderr)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Spotify refresh token rotated\n\n{message}\n")


def build_client():
    refresh_token = require_env("REFRESH_TOKEN")

    oauth = SpotifyOAuth(
        client_id=require_env("CLIENT_ID"),
        client_secret=require_env("CLIENT_SECRET"),
        redirect_uri=os.environ.get("REDIRECT_URI", REDIRECT_URI),
        scope=SCOPE,
        # Keep the token in memory. The old cache_path="token.txt" wrote a
        # credential into the repository root, which the workflow then had to
        # remember to delete before committing.
        cache_handler=MemoryCacheHandler(),
    )

    try:
        token_info = oauth.refresh_access_token(refresh_token)
    except SpotifyOauthError as error:
        sys.exit(
            "[auth] Spotify refused the refresh token.\n"
            f"       {error}\n"
            "       This is the failure that broke the collector on 2026-07-20.\n"
            "       Fix: run `python src/auth_catch.py` to mint a new token, then\n"
            "       update the REFRESH_TOKEN repository secret with the result."
        )

    rotated = token_info.get("refresh_token")
    if rotated and rotated != refresh_token:
        report_rotated_token(rotated)

    # Retry on Spotify's transient 5xx/429 responses rather than losing the run;
    # a lost run is listening history that no longer exists anywhere.
    return spotipy.Spotify(
        auth=token_info["access_token"],
        requests_timeout=30,
        retries=5,
        status_retries=5,
        backoff_factor=0.5,
    )


sp = build_client()
