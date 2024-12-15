from itertools import islice
import os

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
