from Classes import *


recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()

[print(i, song) for i, song in enumerate(recentlyPlayedSongs)]
