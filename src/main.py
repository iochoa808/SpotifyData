from Classes import *


#recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()

#[print(song) for song in recentlyPlayedSongs]

recent = sp.current_user_recently_played()

print(recent['items'][0].keys(), recent['items'][0]['track'].keys())

# Played at name
# datetime(recent['items'][0]['played_at']) + recent['items'][0]['track']['name']