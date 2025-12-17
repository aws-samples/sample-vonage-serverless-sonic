import asyncio
import base64
import json
import logging
import os
import uuid
import requests
from datetime import datetime
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

MODEL_ID = "amazon.nova-sonic-v1:0"
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
VOICE_ID = os.getenv("VOICE_ID", "tiffany")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a friendly phone assistant. Keep responses short and conversational.")


def get_imdsv2_token():
    try:
        response = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            timeout=2,
        )
        if response.status_code == 200:
            return response.text
    except Exception:
        pass
    return None


def get_credentials_from_imds():
    result = {"success": False, "credentials": None, "error": None}
    try:
        token = get_imdsv2_token()
        headers = {"X-aws-ec2-metadata-token": token} if token else {}
        role_response = requests.get(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            headers=headers,
            timeout=2,
        )
        if role_response.status_code != 200:
            result["error"] = f"Failed to get role name: HTTP {role_response.status_code}"
            return result
        role_name = role_response.text.strip()
        creds_response = requests.get(
            f"http://169.254.169.254/latest/meta-data/iam/security-credentials/{role_name}",
            headers=headers,
            timeout=2,
        )
        if creds_response.status_code != 200:
            result["error"] = f"Failed to get credentials: HTTP {creds_response.status_code}"
            return result
        credentials = creds_response.json()
        result["success"] = True
        result["credentials"] = credentials
    except Exception as e:
        result["error"] = f"IMDS error: {str(e)}"
    return result


def setup_credentials():
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        logger.info("Using existing environment credentials")
        return True
    logger.info("Fetching credentials from IMDS...")
    imds_result = get_credentials_from_imds()
    if imds_result["success"]:
        creds = imds_result["credentials"]
        os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
        os.environ["AWS_SESSION_TOKEN"] = creds["Token"]
        logger.info("Credentials loaded from IMDS successfully")
        return True
    else:
        logger.error(f"Failed to get credentials: {imds_result['error']}")
        return False


class NovaSonicBridge:
    def __init__(self):
        self.stream = None
        self.is_active = False
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        self.audio_chunks_sent = 0
        self.response_task = None
        
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{REGION}.amazonaws.com",
            region=REGION,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.client = BedrockRuntimeClient(config=config)

    async def _send(self, event: dict):
        if self.stream and self.is_active:
            try:
                chunk = InvokeModelWithBidirectionalStreamInputChunk(
                    value=BidirectionalInputPayloadPart(bytes_=json.dumps(event).encode())
                )
                await self.stream.input_stream.send(chunk)
            except Exception as e:
                logger.error(f"Error sending to Nova Sonic: {e}", exc_info=True)
                self.is_active = False
                raise

    async def start(self, send_audio_callback):
        try:
            logger.info("Connecting to Nova Sonic...")
            self.stream = await self.client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID)
            )
            self.is_active = True
            logger.info("Stream connected")

            self.response_task = asyncio.create_task(self._process_responses(send_audio_callback))
            await asyncio.sleep(0.1)

            await self._send({
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": 1024,
                            "topP": 0.9,
                            "temperature": 0.7
                        }
                    }
                }
            })
            await asyncio.sleep(0.1)

            await self._send({
                "event": {
                    "promptStart": {
                        "promptName": self.prompt_name,
                        "textOutputConfiguration": {"mediaType": "text/plain"},
                        "audioOutputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 16000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "voiceId": VOICE_ID,
                            "encoding": "base64",
                            "audioType": "SPEECH"
                        },
                        "toolUseOutputConfiguration": {
                            "mediaType": "application/json"
                        },
                        "toolConfiguration": {
                            "tools": [
                                {
                                    "toolSpec": {
                                        "name": "getDateTool",
                                        "description": "get information about the current day",
                                        "inputSchema": {
                                            "json": '''{
                                                "type": "object",
                                                "properties": {},
                                                "required": []
                                            }'''
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            })
            await asyncio.sleep(0.1)

            await self._send({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name,
                        "type": "TEXT",
                        "interactive": False,
                        "role": "SYSTEM",
                        "textInputConfiguration": {"mediaType": "text/plain"}
                    }
                }
            })
            await asyncio.sleep(0.05)
            
            await self._send({
                "event": {
                    "textInput": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name,
                        "content": SYSTEM_PROMPT
                    }
                }
            })
            await asyncio.sleep(0.05)
            
            await self._send({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name
                    }
                }
            })
            await asyncio.sleep(0.1)

            await self._send({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": self.audio_content_name,
                        "type": "AUDIO",
                        "interactive": True,
                        "role": "USER",
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 16000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "audioType": "SPEECH",
                            "encoding": "base64"
                        }
                    }
                }
            })
            logger.info("Nova Sonic ready for audio")

        except Exception as e:
            logger.error(f"Failed to start Nova Sonic session: {e}", exc_info=True)
            self.is_active = False
            raise

    async def send_audio(self, pcm_bytes: bytes):
        if not self.is_active:
            return
            
        self.audio_chunks_sent += 1
        
        await self._send({
            "event": {
                "audioInput": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name,
                    "content": base64.b64encode(pcm_bytes).decode()
                }
            }
        })

    async def _process_responses(self, send_callback):
        role = None
        
        try:
            while self.is_active:
                try:
                    output = await self.stream.await_output()
                    result = await output[1].receive()
                except Exception as e:
                    logger.error(f"Error in response processor: {type(e).__name__}: {e}", exc_info=True)
                    raise
                
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    json_data = json.loads(response_data)
                    
                    if 'event' in json_data:
                        event = json_data['event']
                        event_type = list(event.keys())[0] if event else 'unknown'
                        
                        if event_type != 'audioOutput':
                            logger.info(f"Event: {event_type}")
                        
                        if 'contentStart' in event:
                            content_start = event['contentStart']
                            role = content_start.get('role', '')
                            
                        elif 'textOutput' in event:
                            text_content = event['textOutput'].get('content', '')
                            text_role = event['textOutput'].get('role', role)
                            if text_content:
                                logger.info(f"[{text_role}] {text_content}")
                                
                        elif 'audioOutput' in event:
                            audio_content = event['audioOutput'].get('content', '')
                            if audio_content:
                                audio_bytes = base64.b64decode(audio_content)
                                await send_callback(audio_bytes)
                    
        except asyncio.CancelledError:
            pass
        except StopAsyncIteration:
            pass
        except Exception as e:
            logger.error(f"Fatal error in response processor: {e}", exc_info=True)
        finally:
            self.is_active = False

    async def stop(self):
        if not self.is_active:
            return
            
        self.is_active = False
        
        try:
            await self._send({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.audio_content_name
                    }
                }
            })
            await asyncio.sleep(0.05)
            
            await self._send({
                "event": {
                    "promptEnd": {
                        "promptName": self.prompt_name
                    }
                }
            })
            await asyncio.sleep(0.05)
            
            await self._send({
                "event": {
                    "sessionEnd": {}
                }
            })
            
            await self.stream.input_stream.close()
        except Exception as e:
            logger.error(f"Error closing Nova Sonic session: {e}")
        
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            try:
                await self.response_task
            except asyncio.CancelledError:
                pass


@app.on_event("startup")
async def startup():
    setup_credentials()


@app.get("/")
@app.get("/health")
@app.get("/ping")
async def health():
    return JSONResponse({"status": "healthy"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    logger.info(f"Vonage connecting from {websocket.client}")
    await websocket.accept()

    bridge = NovaSonicBridge()
    first_message = True

    async def send_to_vonage(audio: bytes):
        try:
            await websocket.send_bytes(audio)
        except Exception as e:
            logger.error(f"Error sending to Vonage: {e}")

    try:
        await bridge.start(send_to_vonage)
        logger.info("Nova Sonic bridge started")

        while bridge.is_active:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            if msg.get("type") == "websocket.disconnect":
                logger.info("Vonage disconnected")
                break

            if first_message and "text" in msg:
                first_message = False
                continue

            if "bytes" in msg:
                audio_data = msg["bytes"]
                await bridge.send_audio(audio_data)

    except WebSocketDisconnect:
        logger.info("Vonage WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        await bridge.stop()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
