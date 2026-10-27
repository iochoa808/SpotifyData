from itertools import islice
import os
from datetime import datetime, timezone

GITHUB_PATH = './data'
LOCAL_PATH = os.path.join(os.path.dirname(__file__), '..', 'data')


# Utility function to split a list into batches
def batch(iterable, n=20):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def get_data_path():
    # Running in GitHub Actions
    if os.getenv('GITHUB_ACTIONS') == 'true':
        return GITHUB_PATH
    return LOCAL_PATH


def toTimestamp(date):
    """Spotify's UTC played_at string -> UTC epoch seconds.

    The trailing 'Z' means UTC, so the parsed value has to be tagged as UTC
    before .timestamp() is taken. Without the tzinfo, Python reads it in the
    machine's own zone and the result moves with the runner: the same play came
    out as 1784532876 under UTC but 1784525676 under Europe/Madrid. Since this
    value is the primary key of recently_played.csv, that silently forked the
    history whenever the script ran anywhere but the UTC CI runner.
    """
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(date, pattern)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    raise ValueError(f"Unrecognised Spotify timestamp: {date!r}")


def toDateTime(timestamp):
    """UTC epoch seconds -> aware datetime in the local zone, for display.

    Replaces a hardcoded +1 hour, which was only right for half the year.
    """
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone()


def getItemsFromAPICall(itemsObj):
    # Imported here rather than at module scope: Spotify.py builds its client on
    # import, so a top-level import would make this module unusable without
    # credentials — including under test.
    from Spotify import sp

    results = []
    while itemsObj:
        results.extend(item for item in itemsObj['items'])
        itemsObj = sp.next(itemsObj) if itemsObj['next'] else None

    return results


def getValueFromNestedDictionary(data, path, separator='.'):
    # If the path is empty, return the current data
    if not path:
        return data

    keys = path.split(separator, 1)  # Split into the first key and the remaining path
    key = keys[0]
    remaining_path = keys[1] if len(keys) > 1 else None

    # Apply the function recursively to each element in the list
    if isinstance(data, list):
        return [getValueFromNestedDictionary(item, path, separator) for item in data]

    # Recurse into the next level with the remaining path
    elif isinstance(data, dict) and key in data:

        # Get all the items from Spotipy and recurse into the next level with the remaining path
        if 'next' in data:
            keys = remaining_path.split(separator, 1)
            key = keys[0]
            remaining_path = keys[1] if len(keys) > 1 else None

            return [getValueFromNestedDictionary(item[key], remaining_path, separator)
                    for item in getItemsFromAPICall(data)]

        # Recurse into the next level with the remaining path
        else:
            return getValueFromNestedDictionary(data[key], remaining_path, separator) if remaining_path else data[key]

    # If the key is not found, return None
    else:
        return None


def print_keys(d, indent=0):
    for key, value in d.items():
        print(" " * indent + str(key))
        if isinstance(value, dict):  # If the value is a dictionary, go deeper
            print_keys(value, indent + 4)
