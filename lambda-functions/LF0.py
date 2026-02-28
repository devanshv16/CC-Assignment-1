import json
import boto3
import uuid
import os

client = boto3.client('lexv2-runtime')

BOT_ID = "QYTISLQ7J4"
BOT_ALIAS_ID = "OOGXUKVDVL"
LOCALE_ID = "en_US"


def lambda_handler(event, context):

    print("EVENT:", event)

    # Handle both API Gateway and direct payload
    if 'body' in event:
        body = json.loads(event['body'])
    else:
        body = event

    user_message = body['messages'][0]['unstructured']['text']

    #session_id = str(uuid.uuid4())
    session_id = "user123"

    response = client.recognize_text(
        botId=BOT_ID,
        botAliasId=BOT_ALIAS_ID,
        localeId=LOCALE_ID,
        sessionId=session_id,
        text=user_message
    )

    lex_message = response['messages'][0]['content']

    return {
    "messages": [
        {
            "type": "unstructured",
            "unstructured": {
                "text": lex_message
            }
        }
    ]
}