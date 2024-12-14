import pandas as pd
import csv
import os

DATA = ".\\data"

def readTracks(filename, filePath=""):

    columns = ["Datetime", "Title", "Artist", "Track_ID", "Spotify_Link", "ISRC"]

    # Read the CSV file into a pandas DataFrame
    df = pd.read_csv(filePath+filename, header=None, names=columns)

    # Convert the "Datetime" column to datetime format
    df["Datetime"] = pd.to_datetime(df["Datetime"], format="%B %d, %Y at %I:%M%p")

    return df



# Function to check if an instance exists in the CSV
def instanceExists(file_path, unique_value, unique_attribute="id"):
    if not os.path.exists(file_path):
        return False  # File doesn't exist, so instance cannot exist

    with open(file_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row[unique_attribute] == unique_value:
                return True
    return False


def saveInstanceToCSV(instance, file_path, unique_attribute="id"):
    attributes = vars(instance)
    full_path = os.path.join(DATA, file_path)
    file_exists = os.path.exists(full_path)

    # Check if the instance already exists
    if instanceExists(full_path, attributes[unique_attribute], unique_attribute):
        return None

    # Write to CSV
    with open(full_path, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=attributes.keys())
        
        # Write headers if the file is being created
        if not file_exists:
            writer.writeheader()
        
        # Write the instance data
        writer.writerow(attributes)
