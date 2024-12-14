from spotipy.oauth2 import SpotifyOAuth
import spotipy

from dotenv import load_dotenv
import os


sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://localhost:8888/callback",
    scope="user-read-recently-played"
))