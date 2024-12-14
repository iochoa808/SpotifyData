from spotipy.oauth2 import SpotifyOAuth
import spotipy

from dotenv import load_dotenv
import os

print("BEFORE LOADENV")

load_dotenv()

print(f"CLIENT_ID: {os.getenv('CLIENT_ID')}")
print(f"CLIENT_SECRET: {os.getenv('CLIENT_SECRET')}")

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://localhost:8888/callback",
    scope="user-read-recently-played"
))

print("SPOTIPY INITIATED")
