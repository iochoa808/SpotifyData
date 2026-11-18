from Classes import *
import os


def report(count):
    """Hand the play count to the workflow, which uses it in the commit message
    and the run summary. A no-op outside GitHub Actions."""
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"plays={count}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### {count} new play{'' if count == 1 else 's'} collected\n")


def saveRecentlyPlayedSongs(show=True):
    recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
    if show:
        [print(i + 1, song) for i, song in enumerate(recentlyPlayedSongs)]
        print(f"\n{len(recentlyPlayedSongs)} new songs stored")
    report(len(recentlyPlayedSongs))


saveRecentlyPlayedSongs()
