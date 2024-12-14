from spotipy.oauth2 import SpotifyOAuth
import spotipy

import os

print("BEFORE LOADENV")

sp_oauth = SpotifyOAuth(
    client_id=os.environ["CLIENT_ID"],
    client_secret=os.environ["CLIENT_SECRET"],
    redirect_uri="http://localhost:8888/callback",
    scope="user-read-recently-played",
    cache_path="token.txt"
)

token_info = sp_oauth.refresh_access_token(os.environ["REFRESH_TOKEN"])
access_token = token_info["access_token"]

sp = spotipy.Spotify(auth=access_token)

print("SPOTIPY INITIATED")
