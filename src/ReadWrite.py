import csv
import os
import utils
import ast

DATA = utils.get_data_path()

# One set of primary keys per CSV, built on first use and kept current as rows
# are appended. The existence check used to re-read the whole file for every
# object, twice for every new one — about 95 seconds of scanning per run against
# a 48k-row recently_played.csv, growing with the history forever.
_id_cache = {}


def _open_csv(full_path):
    # Older rows were written by a Windows runner and are not all valid UTF-8.
    try:
        return open(full_path, mode='r', newline='', encoding='utf-8')
    except UnicodeDecodeError:
        return open(full_path, mode='r', newline='', encoding='windows-1252')


def loadIds(file_path, unique_attribute="id"):
    """Primary keys already stored in this CSV. Read once, then cached."""
    if file_path in _id_cache:
        return _id_cache[file_path]

    ids = set()
    full_path = os.path.join(DATA, file_path)
    if os.path.exists(full_path):
        try:
            with _open_csv(full_path) as file:
                for row in csv.DictReader(file):
                    raw = row.get(unique_attribute)
                    if raw is not None:
                        ids.add(parse_value(raw))
        except UnicodeDecodeError:
            with open(full_path, mode='r', newline='', encoding='windows-1252') as file:
                for row in csv.DictReader(file):
                    raw = row.get(unique_attribute)
                    if raw is not None:
                        ids.add(parse_value(raw))

    _id_cache[file_path] = ids
    return ids


def idExists(file_path, unique_value, unique_attribute="id"):
    """Membership test only. Use instanceExists when the row itself is needed."""
    return unique_value in loadIds(file_path, unique_attribute)


def latestId(file_path, unique_attribute="id"):
    """Largest numeric key in the CSV, or None.

    recently_played.csv is append-ordered rather than sorted, so the last line
    is not reliably the newest play.
    """
    numeric = [i for i in loadIds(file_path, unique_attribute) if isinstance(i, int)]
    return max(numeric) if numeric else None


# Function to check if an instance exists in the CSV
def instanceExists(file_path, unique_value, unique_attribute="id"):
    full_path = os.path.join(DATA, file_path)
    if not os.path.exists(full_path):
        return None  # File doesn't exist, so instance cannot exist

    # Open the file with fallback encoding
    try:
        with open(full_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                typed_row = {key: parse_value(value) for key, value in row.items()}
                if typed_row.get(unique_attribute) == unique_value:
                    return typed_row

    # Fallback to a more forgiving encoding
    except UnicodeDecodeError:
        with (open(full_path, mode='r', newline='', encoding='windows-1252') as file):
            reader = csv.DictReader(file)
            for row in reader:
                typed_row = {key: parse_value(value) for key, value in row.items()}
                if typed_row.get(unique_attribute) == unique_value:
                    return typed_row

    return False


def saveInstanceToCSV(instance, file_path):
    attributes = vars(instance)
    full_path = os.path.join(DATA, file_path)
    file_exists = os.path.exists(full_path)

    # Write to CSV with UTF-8 encoding
    with open(full_path, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=attributes.keys())

        # Write headers if the file is being created
        if not file_exists:
            writer.writeheader()

        # Write the instance data
        writer.writerow(attributes)

    # Keep the cache in step so the row is found without re-reading the file.
    if file_path in _id_cache:
        _id_cache[file_path].add(getattr(instance, 'id', None))


def parse_value(value):
    if value.startswith('[') and value.endswith(']'):
        # Attempt to parse as a list
        try:
            return ast.literal_eval(value)  # Safely evaluate the string as a Python list
        except (ValueError, SyntaxError):
            return value  # Fallback to the original string if parsing fails
    if value.isdigit():
        return int(value)  # Convert numeric strings to integers
    if value.lower() in {'true', 'false'}:
        return value.lower() == 'true'  # Convert "true"/"false" to boolean
    try:
        return float(value)  # Convert numeric strings to float if applicable
    except ValueError:
        return value  # Return the original string for all other cases