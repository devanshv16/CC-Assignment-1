import os
import json
import random
import boto3
import base64
import urllib.request
import urllib.error
import traceback
from datetime import datetime, timezone

REGION = "us-east-1"

ses = boto3.client("ses", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

OS_HOST = os.environ["OS_HOST"]          # NO https, NO trailing /
OS_USER = os.environ["OS_USER"]
OS_PASS = os.environ["OS_PASS"]
DDB_TABLE = os.environ["DDB_TABLE"]
SES_SOURCE = os.environ["SES_SOURCE"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]

INDEX_NAME = "restaurants"
table = dynamodb.Table(DDB_TABLE)

NYC_UMBRELLA = ["New York", "Manhattan", "Brooklyn", "Queens"]
NYC_ALIASES = {"new york", "new york city", "nyc"}

CUISINE_UMBRELLA = {
    "asian": ["Chinese", "Japanese", "Thai"]
}

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def lambda_handler(event, context):
    print("=== LF2 START ===", now_utc())
    print("Event keys:", list(event.keys()) if isinstance(event, dict) else type(event))

    # If you ever manually test with Records
    if isinstance(event, dict) and event.get("Records"):
        for record in event["Records"]:
            body = json.loads(record["body"])
            process_one_request(body)
        print("=== LF2 END (Records mode) ===", now_utc())
        return {"statusCode": 200, "body": "Success"}

    processed = poll_and_process_sqs(max_messages=1)
    print(f"Processed {processed} message(s) this run.")
    print("=== LF2 END (poll mode) ===", now_utc())
    return {"statusCode": 200, "body": f"Processed {processed} message(s)"}


def poll_and_process_sqs(max_messages=1):
    """
    Poll SQS directly (EventBridge schedule invokes LF2 every minute).
    One-message processing keeps behavior easy to reason about.
    """
    resp = sqs.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        MaxNumberOfMessages=min(10, max_messages),
        WaitTimeSeconds=10,              # long poll
        VisibilityTimeout=180,           # give yourself time to call OS + DDB + SES
        MessageAttributeNames=["All"],
        AttributeNames=["All"],          # <-- IMPORTANT for debugging delays/retries
    )

    messages = resp.get("Messages", [])
    if not messages:
        print("No messages received from SQS.")
        return 0

    processed = 0

    for msg in messages:
        receipt_handle = msg["ReceiptHandle"]
        msg_id = msg.get("MessageId")
        attrs = msg.get("Attributes", {})

        print("---- SQS MESSAGE RECEIVED ----")
        print("MessageId:", msg_id)
        print("SentTimestamp:", attrs.get("SentTimestamp"))
        print("FirstReceiveTimestamp:", attrs.get("ApproximateFirstReceiveTimestamp"))
        print("ReceiveCount:", attrs.get("ApproximateReceiveCount"))

        try:
            body = json.loads(msg["Body"])
            print("Body:", body)

            process_one_request(body)

            # delete ONLY if success
            sqs.delete_message(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=receipt_handle
            )
            print("✅ Deleted message from SQS:", msg_id)
            processed += 1

        except Exception as e:
            print("❌ Failed processing message:", msg_id)
            print("Exception:", repr(e))
            print(traceback.format_exc())
            print("Raw message body:", msg.get("Body"))
            # Do NOT delete -> it will reappear after visibility timeout

    return processed


def process_one_request(body: dict):
    cuisine = (body.get("cuisine") or "").strip()
    location = (body.get("location") or "").strip()
    date = body.get("date", "")
    time_ = body.get("time", "")
    people = body.get("people", "")
    to_email = body.get("email")

    if not cuisine or not to_email or not location:
        raise ValueError(f"Missing cuisine/location/email in message: {body}")

    cuisine_candidates = normalize_cuisine(cuisine)
    city_candidates = normalize_location(location)

    restaurant_ids = search_restaurant_ids(
        cuisine_candidates=cuisine_candidates,
        city_candidates=city_candidates
    )

    if not restaurant_ids:
        msg = (
            f"Hello!\n\n"
            f"Sorry — I couldn’t find any {cuisine} restaurants for {location} right now.\n"
            f"Try another cuisine or a different city and I’ll search again.\n"
        )
        send_email(to_email, msg)
        print("✅ Sent 'no results' email to:", to_email)
        return

    chosen_ids = random.sample(restaurant_ids, k=min(3, len(restaurant_ids)))
    restaurants = fetch_restaurants_from_ddb(chosen_ids)

    message_text = format_email(location, cuisine, date, time_, people, restaurants)
    send_email(to_email, message_text)
    print("✅ Sent suggestions email to:", to_email)


def normalize_location(location: str):
    loc = location.strip().lower()
    if loc in NYC_ALIASES:
        return NYC_UMBRELLA
    return [location.strip().title()]


def normalize_cuisine(cuisine: str):
    c = cuisine.strip().lower()
    if c in CUISINE_UMBRELLA:
        return CUISINE_UMBRELLA[c]
    return [cuisine.strip().title()]


def search_restaurant_ids(cuisine_candidates, city_candidates):
    url = f"https://{OS_HOST}/{INDEX_NAME}/_search"

    payload = {
        "size": 200,
        "_source": ["RestaurantID", "Cuisine", "City"],
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [{"match": {"Cuisine": c}} for c in cuisine_candidates],
                            "minimum_should_match": 1
                        }
                    },
                    {
                        "bool": {
                            "should": [{"match": {"City": c}} for c in city_candidates],
                            "minimum_should_match": 1
                        }
                    }
                ]
            }
        }
    }

    token = base64.b64encode(f"{OS_USER}:{OS_PASS}".encode("utf-8")).decode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {token}"}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")  # <-- use POST

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenSearch HTTPError {e.code}: {err}")
    except Exception as e:
        raise RuntimeError(f"OpenSearch request failed: {str(e)}")

    parsed = json.loads(resp_body)
    hits = parsed.get("hits", {}).get("hits", [])

    ids = []
    for h in hits:
        rid = h.get("_source", {}).get("RestaurantID")
        if rid:
            ids.append(rid)

    out, seen = [], set()
    for rid in ids:
        if rid not in seen:
            out.append(rid)
            seen.add(rid)

    print(f"OpenSearch returned {len(out)} candidates for cuisines={cuisine_candidates}, cities={city_candidates}")
    return out


def fetch_restaurants_from_ddb(restaurant_ids):
    results = []
    for rid in restaurant_ids:
        resp = table.get_item(Key={"id": rid})
        item = resp.get("Item")
        if item:
            results.append(item)
        else:
            print("Not found in DynamoDB for id:", rid)
    return results


def format_email(location, cuisine, date, time_, people, restaurants):
    header = (
        f"Hello!\n\n"
        f"Here are your dining suggestions for {cuisine} food in {location}\n"
        f"for {people} people on {date} at {time_}.\n\n"
    )

    if not restaurants:
        return header + "Sorry — I found matches in OpenSearch, but couldn’t fetch details from DynamoDB.\n"

    lines = []
    for i, r in enumerate(restaurants, start=1):
        name = r.get("name", "Unknown")
        address = r.get("address", "Unknown address")
        rating = r.get("rating", "N/A")
        reviews = r.get("review_count", "N/A")
        zip_code = (r.get("zip_code") or "").strip()

        # Prevent duplicate zip code if it's already part of the address
        addr_line = address
        if zip_code and zip_code not in address:
            addr_line = f"{address} {zip_code}"

        lines.append(
            f"{i}) {name}\n"
            f"   Address: {addr_line}\n"
            f"   Rating: {rating} ({reviews} reviews)\n"
        )

    return header + "\n".join(lines) + "\nEnjoy your meal!\n"

def send_email(to_email, message_text):
    # SES failures are common in sandbox / unverified recipients — make them loud.
    resp = ses.send_email(
        Source=SES_SOURCE,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": "Your Dining Suggestions"},
            "Body": {"Text": {"Data": message_text}},
        },
    )
    print("SES MessageId:", resp.get("MessageId"))