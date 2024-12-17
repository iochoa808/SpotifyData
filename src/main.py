from Classes import *

recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
[print(i, song) for i, song in enumerate(recentlyPlayedSongs)]
print(f"\n\n{len(recentlyPlayedSongs)} new songs stored")

# Played at name
# datetime(recent['items'][0]['played_at']) + recent['items'][0]['track']['name']
