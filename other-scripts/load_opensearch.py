import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from decimal import Decimal

# =====================
# CONFIG
# =====================
region = "us-east-1"
index_name = "restaurants"
ddb_table_name = "Restaurants"

# OpenSearch domain endpoint (NOT dashboards URL)
host = "search-restaurants-ymxiguso37nfvasgqnuudfi4xm.us-east-1.es.amazonaws.com"
port = 443

# If you're using master user/pass auth:
auth = ("devanshv16", "Devansh99@")  # consider moving to env vars

client = OpenSearch(
    hosts=[{"host": host, "port": port}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

# =====================
# DynamoDB scan (handles pagination)
# =====================
dynamodb = boto3.resource("dynamodb", region_name=region)
table = dynamodb.Table(ddb_table_name)

items = []
resp = table.scan()
items.extend(resp.get("Items", []))
while "LastEvaluatedKey" in resp:
    resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
    items.extend(resp.get("Items", []))

print(f"Found {len(items)} restaurants in DynamoDB")

# =====================
# Index into OpenSearch
# =====================
for item in items:
    rid = item.get("id")
    if not rid:
        continue

    doc = {
        "RestaurantID": rid,
        "Cuisine": item.get("cuisine", "Unknown"),
        # OPTIONAL but useful:
        "City": item.get("city", "Unknown")
    }

    client.index(index=index_name, id=rid, body=doc)

print("✅ Data loaded into OpenSearch")