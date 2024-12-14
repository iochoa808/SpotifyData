import datetime
import json
from Classes import *
from Spotify import sp
from ReadWrite import *
from pprint import pprint


def toDateTime(spotiDateTime):
     return datetime.datetime.strptime(spotiDateTime.split('.')[0].rstrip('Z'), "%Y-%m-%dT%H:%M:%S")

def showTracks(tracks, i=0):
    # Display the tracks
    for idx, item in enumerate(tracks):
        track = item['track']
        try:
            dateTime = toDateTime(item['played_at'])
            print(f"{idx+1+i}: [{dateTime}] {track['name']} by {', '.join(artist['name'] for artist in track['artists'])}")
        except:
            print(f"{idx+1+i}: {track['name']} by {', '.join(artist['name'] for artist in track['artists'])}")

print("MAIN")

RecentlyPlayedSongs.saveRecentlyPlayedSongs()

print("RECENTLYPLAYED EXECUTED")
