import csv
import os
import utils

DATA = utils.get_data_path()


# Function to check if an instance exists in the CSV
def instanceExists(file_path, unique_value, unique_attribute="id"):
    full_path = os.path.join(DATA, file_path)
    if not os.path.exists(full_path):
        return False  # File doesn't exist, so instance cannot exist

    # Open the file with fallback encoding
    try:
        with open(full_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row[unique_attribute] == unique_value:
                    return True
    except UnicodeDecodeError:
        # Fallback to a more forgiving encoding
        with open(full_path, mode='r', newline='', encoding='windows-1252') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row[unique_attribute] == unique_value:
                    return True

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
