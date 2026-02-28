import requests
import boto3
import json
import time
from decimal import Decimal

# ========================
# CONFIG
# ========================

API_KEY = "API_KEY"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}"
}

DYNAMODB_TABLE = "Restaurants"

cities = [
    "New York",
    "Manhattan",
    "Brooklyn",
    "Queens",
    "Chicago",
    "Los Angeles",
    "San Francisco",
    "Boston",
    "Seattle",
    "Austin",
    "Miami"
]

cuisines = [
    "Italian",
    "Chinese",
    "Indian",
    "Mexican",
    "Japanese",
    "Thai",
    "American",
    "Mediterranean",
    "French",
    "Spanish"
]

# ========================
# AWS DynamoDB
# ========================

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table(DYNAMODB_TABLE)


# ========================
# Helpers
# ========================

def to_decimal(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


# ========================
# Yelp Fetch
# ========================

def fetch_restaurants(city, cuisine):

    url = "https://api.yelp.com/v3/businesses/search"

    params = {
        "term": cuisine,
        "location": city,
        "limit": 20
    }

    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code != 200:
        print("Error:", response.text)
        return []

    return response.json().get("businesses", [])


# ========================
# Store in DynamoDB
# ========================

def store_restaurant(business, cuisine):

    location = business.get("location", {})
    coordinates = business.get("coordinates", {})

    item = {
        # REQUIRED FIELDS
        "id": business.get("id"),  # Partition Key

        "name": business.get("name"),
        "address": " ".join(location.get("display_address", [])),
        "city": location.get("city"),
        "zip_code": location.get("zip_code"),

        "latitude": to_decimal(coordinates.get("latitude")),
        "longitude": to_decimal(coordinates.get("longitude")),

        "review_count": business.get("review_count", 0),

        "rating": to_decimal(business.get("rating")),

        "cuisine": cuisine
    }

    # Skip if ID missing
    if not item["id"]:
        return

    table.put_item(Item=item)


# ========================
# MAIN
# ========================

all_data = []

for city in cities:
    for cuisine in cuisines:

        print(f"Fetching {cuisine} in {city}")

        businesses = fetch_restaurants(city, cuisine)

        for b in businesses:

            # Save raw for backup file
            all_data.append(b)

            # Store in DynamoDB
            store_restaurant(b, cuisine)

        time.sleep(1)  # Avoid Yelp rate limit


# Backup locally
with open("restaurants.json", "w") as f:
    json.dump(all_data, f, indent=2)

print("✅ Done. Data stored in DynamoDB.")