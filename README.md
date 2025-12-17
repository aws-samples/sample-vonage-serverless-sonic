# Real-Time Voice Agent with Amazon Bedrock Nova Sonic

by Reilly Manton

A serverless voice agent that enables natural, interruptible phone conversations using Amazon Bedrock's Nova Sonic model and AWS AgentCore Runtime's bidirectional streaming capabilities.

## Overview

This project demonstrates how to build a production-ready voice agent that handles phone calls through the Vonage Voice API, processing audio in real-time with Amazon Bedrock's Nova Sonic model.

AgentCore Runtime's bidirectional streaming support enables natural, interruptible conversations over WebSocket connections. Previously, connecting Nova Sonic to voice APIs over the phone required managing EC2, ECS, or EKS infrastructure to handle the WebSocket connections. AgentCore Runtime provides a serverless, purpose-built agent runtime environment that manages these voice API connections without requiring container orchestration or server provisioning.

## Architecture

```
Phone Call → Vonage Voice API → API Gateway (HTTP) → Lambda (Webhook Handler)
                                                        ↓
                                                   Generates presigned URL
                                                        ↓
             Vonage ← WebSocket Connection ← AgentCore Runtime → Nova Sonic
                                                        ↓
                                                   Audio Response
```

The application uses a two-tier architecture:

1. **Lambda Webhook Handler**: Receives Vonage webhook calls and generates presigned WebSocket URLs for AgentCore Runtime
2. **AgentCore Runtime**: Bridges Vonage's WebSocket audio stream (16kHz, 16-bit PCM) directly to Amazon Bedrock's Nova Sonic model

This enables:
- Continuous audio input processing
- Real-time speech-to-text transcription
- Natural language understanding and response generation
- Text-to-speech audio output streaming back to the caller

## Prerequisites

- AWS Account with Bedrock access
- Amazon Nova Sonic model enabled in your AWS region
- Vonage API account
- Python 3.12+
- AWS CDK (for deployment)

## Project Structure

```
.
├── .env
├── lambda/
│   └── api/
│       ├── index.py           # Vonage webhook handler
│       └── requirements.txt   # Lambda dependencies
├── runtime/
│   ├── index.py               # AgentCore Runtime application
│   ├── requirements.txt       # Runtime dependencies
│   └── Dockerfile             # Container configuration
└── cdk/
    ├── lib/
    │   └── cdk-stack.ts       # Infrastructure as code
    └── bin/
        └── cdk.ts             # CDK app entry point
```

## Deployment

### 1. Prerequisites

- AWS account w/ CDK bootstrap complete
- AWS CLI configured with appropriate credentials
- Node.js and npm installed
- Docker installed and running (for building the runtime container)

### ### 2. Create a Vonage Application

1. Create a Vonage application in the Vonage Dashboard and capture the `APPLICATION ID` from the Vonage console.
2. Copy .env.template to a new file .env and add your vonage application ID.  

### 2. Deploy Infrastructure

```bash
cd cdk
npm install
cdk deploy
```

### 3. Configure Vonage

After deployment, the CDK will output the API Gateway URLs. Configure your Vonage application:

1. Go to the vonage application page where you previously got your application ID.
2. Set the **Answer URL** to the `AnswerUrl` output (e.g., `https://xxx.execute-api.us-east-1.amazonaws.com/vonage/answer`)
3. Set the **Event URL** to the `EventUrl` output (e.g., `https://xxx.execute-api.us-east-1.amazonaws.com/vonage/event`)
4. Set the **Fallback URL** to the `FallbackUrl` output (e.g., `https://xxx.execute-api.us-east-1.amazonaws.com/vonage/fallback`)
4. Configure a phone number to use the application



## How It Works

### 1. Incoming Call

When a call comes in, Vonage sends an HTTP GET request to the `/vonage/answer` endpoint.

### 2. Presigned URL Generation

The Lambda function:
- Receives the webhook with call metadata (UUID, caller number)
- Generates a presigned WebSocket URL for the AgentCore Runtime (valid for 5 minutes)
- Returns an NCCO (Nexmo Call Control Object) instructing Vonage to connect to the WebSocket

### 3. WebSocket Connection

Vonage establishes a WebSocket connection to the AgentCore Runtime using the presigned URL. The first message contains metadata about the call.

### 4. Audio Streaming

Vonage streams raw PCM audio (16kHz, 16-bit, mono) in 20ms chunks (640 bytes). The application:
- Receives audio chunks via WebSocket
- Base64 encodes and forwards to Nova Sonic
- Maintains the bidirectional stream connection

### 5. Response Processing

Nova Sonic processes the audio stream and returns:
- Speech-to-text transcriptions
- Natural language responses (text)
- Text-to-speech audio output

The application streams audio responses back to Vonage in real-time.

## Key Components

### Lambda Webhook Handler (`lambda/api/index.py`)

Handles Vonage webhook callbacks:
- `/vonage/answer`: Generates presigned WebSocket URL and returns NCCO
- `/vonage/event`: Logs call events (start, end, etc.)
- `/vonage/fallback`: Handles connection failures

### AgentCore Runtime (`runtime/index.py`)

#### NovaSonicBridge Class

Manages the bidirectional stream with Nova Sonic:
- Session initialization with system prompt
- Audio input/output configuration
- Event processing (transcriptions, audio, usage)
- Graceful session cleanup

#### WebSocket Handler

Bridges Vonage and Nova Sonic:
- Accepts incoming WebSocket connections
- Routes audio between Vonage and Nova Sonic
- Handles connection lifecycle

## Configuration

The runtime uses the following defaults (hardcoded in `runtime/index.py`):

- **Voice ID**: `tiffany`
- **System Prompt**: "You are a friendly phone assistant. Keep responses short and conversational."
- **Region**: `us-east-1`

To customize these, modify the values in `runtime/index.py`:

```python
MODEL_ID = "amazon.nova-sonic-v1:0"
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
VOICE_ID = os.getenv("VOICE_ID", "tiffany")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a friendly phone assistant. Keep responses short and conversational.")
```

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
