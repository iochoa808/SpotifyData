from Classes import *


recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()

[print(i, song) for i, song in enumerate(recentlyPlayedSongs)]

print(f"\n\n{len(recentlyPlayedSongs)} stored in recentlyPlayedSongs")

# Played at name
# datetime(recent['items'][0]['played_at']) + recent['items'][0]['track']['name']