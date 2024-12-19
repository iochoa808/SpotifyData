import csv
import os
import utils
import ast

DATA = utils.get_data_path()


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
                if row[unique_attribute] == unique_value:
                    return typed_row

    # Fallback to a more forgiving encoding
    except UnicodeDecodeError:
        with (open(full_path, mode='r', newline='', encoding='windows-1252') as file):
            reader = csv.DictReader(file)
            for row in reader:
                typed_row = {key: parse_value(value) for key, value in row.items()}
                if row[unique_attribute] == unique_value:
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