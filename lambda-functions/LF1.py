import json
import os
import boto3
from datetime import datetime
from zoneinfo import ZoneInfo

sqs = boto3.client("sqs")
NY_TZ = ZoneInfo("America/New_York")

QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/925179372031/Q1").strip()
VERIFIED_EMAIL = os.environ.get("VERIFIED_EMAIL", "").strip().lower()

NYC_ALIASES = {"new york", "new york city", "nyc"}
NYC_UMBRELLA = {"new york", "manhattan", "brooklyn", "queens"}  # no Bronx/Staten

SUPPORTED_CITIES = {
    "new york", "manhattan", "brooklyn", "queens",
    "chicago", "los angeles", "san francisco", "boston", "seattle", "austin", "miami",
    "mumbai", "delhi", "bangalore", "chennai",
}

SUPPORTED_CUISINES = {
    "asian",  # umbrella
    "italian", "chinese", "indian", "mexican", "japanese", "thai",
    "american", "mediterranean", "french", "spanish",
}


# ---------------- Lex helpers ----------------
def get_slot(slots, name):
    s = (slots or {}).get(name)
    if not s or not s.get("value"):
        return None
    v = s["value"]
    return v.get("interpretedValue") or v.get("originalValue")

def clear_slot(slots, name):
    slots[name] = None

def elicit_slot(event, slot_name, message):
    ss = event["sessionState"]
    intent = ss["intent"]
    intent["state"] = "InProgress"
    ss["dialogAction"] = {"type": "ElicitSlot", "slotToElicit": slot_name}
    return {
        "sessionState": ss,
        "messages": [{"contentType": "PlainText", "content": message}],
    }

def delegate(event):
    ss = event["sessionState"]
    ss["intent"]["state"] = "InProgress"
    ss["dialogAction"] = {"type": "Delegate"}
    return {"sessionState": ss}

def close(intent_name, message):
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": intent_name, "state": "Fulfilled"},
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }

def parse_lex_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def parse_lex_time(s):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time()
        except Exception:
            pass
    return None

def normalize_location(location: str):
    if not location:
        return None
    loc = location.strip().lower()
    if loc in NYC_ALIASES:
        return "nyc"  # LF2 expands NYC
    return loc


# ---------------- Validation (validate filled slots every turn) ----------------
def validate_filled_slots(event):
    slots = event["sessionState"]["intent"]["slots"]

    # 1) Location
    loc = get_slot(slots, "location")
    if loc:
        loc_l = loc.strip().lower()
        ok = (loc_l in NYC_ALIASES) or (loc_l in NYC_UMBRELLA) or (loc_l in SUPPORTED_CITIES)
        if not ok:
            clear_slot(slots, "location")
            return elicit_slot(
                event,
                "location",
                f'I don’t have restaurant data for "{loc}". Try New York / Manhattan / Brooklyn / Queens, or Chicago / Los Angeles / Miami.'
            )

    # 2) Cuisine
    cuisine = get_slot(slots, "cuisine")
    if cuisine:
        c_l = cuisine.strip().lower()
        if c_l not in SUPPORTED_CUISINES:
            clear_slot(slots, "cuisine")
            return elicit_slot(
                event,
                "cuisine",
                f'"{cuisine}" isn’t a supported cuisine. Try: Asian, Italian, Chinese, Indian, Mexican, Japanese, Thai, American, Mediterranean, French, Spanish.'
            )

    # 3) Date (today or later)
    d_str = get_slot(slots, "diningDate")
    if d_str:
        d = parse_lex_date(d_str)
        if not d:
            clear_slot(slots, "diningDate")
            return elicit_slot(event, "diningDate", "That date looks invalid. Please enter a valid date (YYYY-MM-DD).")
        today = datetime.now(NY_TZ).date()
        if d < today:
            clear_slot(slots, "diningDate")
            return elicit_slot(event, "diningDate", "Please choose a date that is today or later.")

    # 4) Time (if date is today, must be in the future)
    t_str = get_slot(slots, "diningTime")
    if t_str:
        t = parse_lex_time(t_str)
        if not t:
            clear_slot(slots, "diningTime")
            return elicit_slot(event, "diningTime", "That time looks invalid. Please enter a valid time (HH:MM).")
        if d_str:
            d = parse_lex_date(d_str)
            if d:
                now = datetime.now(NY_TZ)
                if d == now.date():
                    chosen_dt = datetime.combine(d, t, tzinfo=NY_TZ)
                    if chosen_dt <= now:
                        clear_slot(slots, "diningTime")
                        return elicit_slot(event, "diningTime", "For today, please choose a time later than right now.")

    # 5) People (1–10)
    ppl_str = get_slot(slots, "numberOfPeople")
    if ppl_str:
        try:
            ppl = int(ppl_str)
            if ppl < 1 or ppl > 10:
                raise ValueError()
        except Exception:
            clear_slot(slots, "numberOfPeople")
            return elicit_slot(event, "numberOfPeople", "Please enter a number of people between 1 and 10.")

    # 6) Email (must be the one verified)
    email = get_slot(slots, "email")
    if email and VERIFIED_EMAIL and email.strip().lower() != VERIFIED_EMAIL:
        clear_slot(slots, "email")
        return elicit_slot(event, "email", "That email isn’t verified for this system. Please enter the verified email address.")

    return None


# ---------------- Main handler ----------------
def lambda_handler(event, context):
    print("invocationSource =", event.get("invocationSource"))
    print("dialogAction =", json.dumps(event.get("sessionState", {}).get("dialogAction", {})))
    print("slots =", json.dumps(event.get("sessionState", {}).get("intent", {}).get("slots", {})))

    intent = event.get("sessionState", {}).get("intent", {})
    intent_name = intent.get("name", "UnknownIntent")
    source = event.get("invocationSource")

    if intent_name == "GreetingIntent":
        return close(intent_name, "Hi there! How can I help you today?")
    if intent_name == "ThankYouIntent":
        return close(intent_name, "You're welcome! Have a great day.")
    if intent_name != "DiningSuggestionsIntent":
        return close(intent_name, "Sorry, I didn't understand.")

    # Dialog validation
    if source == "DialogCodeHook":
        maybe = validate_filled_slots(event)
        if maybe:
            return maybe
        return delegate(event)

    # Fulfillment: send to SQS (keep your original behavior)
    if source == "FulfillmentCodeHook":
        slots = event["sessionState"]["intent"]["slots"]
        message_body = {
            "location": normalize_location(get_slot(slots, "location")),
            "cuisine": get_slot(slots, "cuisine"),
            "date": get_slot(slots, "diningDate"),
            "time": get_slot(slots, "diningTime"),
            "people": get_slot(slots, "numberOfPeople"),
            "email": get_slot(slots, "email"),
        }
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(message_body))
        return close(intent_name, "Thanks! Your request has been received. You will get restaurant suggestions via email shortly.")

    return close(intent_name, "Sorry — something went wrong.")