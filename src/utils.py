from itertools import islice
import os
from datetime import datetime, timezone, timedelta
from Spotify import sp

GITHUB_PATH = './data'
LOCAL_PATH = os.path.join(os.path.dirname(__file__), '..', 'data')
LOCAL_OFFSET = timedelta(hours=1)

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


def getTimestamp(date):
    return str(datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp())


def flatten_dict(d, sep='_'):
    return {
        f"{key}{sep}{subkey}" if isinstance(value, dict) else key: subvalue
        for key, value in d.items()
        for subkey, subvalue in (value.items() if isinstance(value, dict) else [(key, value)])
    }


def access_dict_path(data, path, separator='.'):
    if not path:  # If the path is empty, return the current data
        return data

    keys = path.split(separator, 1)  # Split into the first key and the remaining path
    key = keys[0]
    remaining_path = keys[1] if len(keys) > 1 else None

    # Apply the function recursively to each element in the list
    if isinstance(data, list):
        return [access_dict_path(item, path, separator) for item in data]
    # Recurse into the next level with the remaining path
    elif isinstance(data, dict) and key in data:
        return access_dict_path(data[key], remaining_path, separator) if remaining_path else data[key]
    # If the key is not found, return None
    else:
        return None

def access_dict_pathNext(data, path, separator='.'):
    if not path:  # If the path is empty, return the current data
        return data

    keys = path.split(separator, 1)  # Split into the first key and the remaining path
    key = keys[0]
    remaining_path = keys[1] if len(keys) > 1 else None

    print(key, data.keys())

    # Apply the function recursively to each element in the list
    if isinstance(data, list):
        return [access_dict_path(item, path, separator) for item in data]

    # NO HI HA ITEMS, FER TRAÇA
    elif isinstance(data, dict) and key in data and 'next' in data:
        tracks, results = [], data
        while results:
            tracks.extend(item[key] for item in results['items'])
            results = sp.next(results) if results['next'] else None

        return [access_dict_path(item, path, separator) for item in tracks]


    # Recurse into the next level with the remaining path
    elif isinstance(data, dict) and key in data:
        return access_dict_path(data[key], remaining_path, separator) if remaining_path else data[key]

    # If the key is not found, return None
    else:
        return None


    """tracks, results = [], query['tracks']
        while results:
            tracks.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None"""