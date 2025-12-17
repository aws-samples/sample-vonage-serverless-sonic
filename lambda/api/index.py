import json
import os
import logging
import base64

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from bedrock_agentcore.runtime import AgentRuntimeClient

AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN")
VONAGE_APPLICATION_ID = os.environ.get("VONAGE_APPLICATION_ID")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def verify_vonage_request(event):
    """Verify the request came from Vonage by checking the JWT claims."""
    if not VONAGE_APPLICATION_ID:
        logger.warning("VONAGE_APPLICATION_ID not set, skipping verification")
        return True
    
    auth_header = event.get('headers', {}).get('authorization', '')
    if not auth_header.startswith('Bearer '):
        logger.warning("Missing or invalid Authorization header")
        return False
    
    try:
        token = auth_header.split(' ')[1]
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        
        if claims.get('application_id') != VONAGE_APPLICATION_ID:
            logger.warning(f"Application ID mismatch: {claims.get('application_id')}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"JWT verification failed: {e}")
        return False


def generate_presigned_url():
    client = AgentRuntimeClient(region=REGION)
    url = client.generate_presigned_url(
        runtime_arn=AGENT_RUNTIME_ARN,
        expires=300
    )
    logger.info(f"Generated presigned URL: {url}")
    return url


def handler(event, context):
    path = event.get("rawPath", event.get("path", ""))
    method = event.get("requestContext", {}).get("http", {}).get("method", 
              event.get("httpMethod", "GET"))
    
    logger.info(f"Request: {method} {path}")
    
    # Verify all Vonage webhook requests
    if path.startswith("/vonage/"):
        if not verify_vonage_request(event):
            return {"statusCode": 401, "body": "Unauthorized"}
    
    if path == "/vonage/answer" and method == "GET":
        query_params = event.get("queryStringParameters") or {}
        call_uuid = query_params.get("uuid", "unknown")
        caller = query_params.get("from", "unknown")
        
        try:
            ws_url = generate_presigned_url()
            ncco = [
                {"action": "talk", "text": "Connecting you now."},
                {
                    "action": "connect",
                    "endpoint": [{
                        "type": "websocket",
                        "uri": ws_url,
                        "content-type": "audio/l16;rate=16000",
                        "headers": {"x-call-uuid": call_uuid, "x-caller": caller}
                    }]
                }
            ]
        except Exception as e:
            logger.error(f"Error: {e}")
            ncco = [{"action": "talk", "text": "Sorry, technical difficulties."}]
        
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(ncco)}
    
    elif path == "/vonage/event" and method == "POST":
        logger.info(f"Event: {event.get('body', '{}')}")
        return {"statusCode": 200, "body": "{}"}
    
    elif path == "/vonage/fallback" and method == "POST":
        ncco = [{"action": "talk", "text": "Sorry, couldn't connect your call."}]
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(ncco)}
    
    return {"statusCode": 404, "body": "Not found"}