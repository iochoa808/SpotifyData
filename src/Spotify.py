from spotipy.oauth2 import SpotifyOAuth
import spotipy

from dotenv import load_dotenv
import os

print("BEFORE LOADENV")

load_dotenv()

sp_oauth = SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://localhost:8888/callback",
    scope="user-read-recently-played",
    cache_path="/tmp/spotify_cache"
)

access_token = sp_oauth.refresh_access_token(refresh_token=os.getenv('REFRESH_TOKEN'))["access_token"]

sp = spotipy.Spotify(auth=access_token)

print("SPOTIPY INITIATED")
