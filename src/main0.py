from dotenv import load_dotenv
import os
import base64
from requests import post, get
import json

load_dotenv()

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")

def getToken():
    auth_string = client_id + ":" + client_secret
    auth_bytes = auth_string.encode("utf-8")
    auth_base64 = str(base64.b64encode(auth_bytes), "utf-8")

    url = "https://accounts.spotify.com/api/token"
    headers = {
        "Authorization" : "Basic " + auth_base64,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}
    result = post(url, headers=headers, data=data)
    json_result = json.loads(result.content)
    token = json_result["access_token"]
    return token

def get_auth_header(token):
    return  {"Authorization": "Bearer " + token}

def formatJSON(jsonString, indent=2):
    return json.dumps(jsonString, indent=indent)

def searchArtist(token, artist_name):
    url = "https://api.spotify.com/v1/search"
    headers = get_auth_header(token)
    query = f"?q={artist_name}&type=artist&limit=1"

    query_url = url + query
    result = get(query_url, headers=headers)
    json_result = json.loads(result.content)["artists"]["items"]

    if len(json_result) == 0:
        print("ERROR")
        return None
    
    return json_result[0]


# Object: 'Album', 'Artist', 'Track', 'Playlist'
def getObjectId(token, object, objId):
    if (object.lower() not in ['album', 'artist', 'track', 'playlist']): return None
    url = f"https://api.spotify.com/v1/{object.lower()}s/{objId}"
    result = get(url, headers=get_auth_header(token))
    return json.loads(result.content)

def getRecentlyPlayedTracks(token):
    url = f"https://api.spotify.com/v1/me/recently-played"




#tracks = readTracks("tracks.csv")

token = getToken()


#print(formatJSON(getObjectId(token, 'artist', "0zooagBp2tYdvvSLp74S7U")))

print(formatJSON(searchArtist(token, 'Radiohead'))) # genres, id, name


"""
playlist = getPlaylist(token, "6bYdhADwAwPJNXrc2i3nSY?si=cba48cd138294e04") # String després de URL
for idx, track in enumerate(playlist['tracks']['items']):
    song = track['track']
    print(f"{idx+1}. {song['name']}, {[artist['name'] for artist in song['artists']]}, [{song['duration_ms']/1000}s]")
"""