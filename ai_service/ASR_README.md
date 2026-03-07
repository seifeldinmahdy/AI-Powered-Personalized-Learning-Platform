# ASR API - Automatic Speech Recognition Service

This API provides automatic speech recognition using OpenAI's Whisper model.

## Features

- Audio file transcription to text
- Support for multiple languages
- Multiple audio format support (WAV, MP3, M4A, etc.)
- Fast inference with Whisper Tiny model
- RESTful API interface

## Setup

### 1. Install Dependencies

```bash
cd ai_service
pip install -r requirements.txt
```

### 2. Run the Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Endpoints

### 1. Transcribe Audio

**Endpoint:** `POST /asr/transcribe`

**Parameters:**
- `audio_file` (file, required): Audio file to transcribe
- `language` (string, optional): Language code (default: 'en')

**Example using cURL:**

```bash
curl -X POST "http://localhost:8000/asr/transcribe" \
  -F "audio_file=@path/to/audio.wav" \
  -F "language=en"
```

**Response:**

```json
{
  "success": true,
  "transcription": "This is the transcribed text",
  "language": "en",
  "inference_time_seconds": 1.234,
  "filename": "audio.wav"
}
```

### 2. ASR Health Check

**Endpoint:** `GET /asr/health`

**Example:**

```bash
curl http://localhost:8000/asr/health
```

**Response:**

```json
{
  "status": "healthy",
  "model_loaded": true
}
```

## Testing

Use the provided test script:

```bash
python test_asr_api.py path/to/audio.wav
```

With custom language:

```bash
python test_asr_api.py path/to/audio.wav es
```

## Python Client Example

```python
import requests

# Transcribe audio file
with open('audio.wav', 'rb') as f:
    files = {'audio_file': f}
    data = {'language': 'en'}
    response = requests.post(
        'http://localhost:8000/asr/transcribe',
        files=files,
        data=data
    )
    result = response.json()
    print(result['transcription'])
```

## Supported Languages

The Whisper model supports multiple languages including:
- English (en)
- Spanish (es)
- French (fr)
- German (de)
- Italian (it)
- Portuguese (pt)
- And many more...

## API Documentation

Interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Notes

- First request may be slower as the model loads into memory
- The Whisper Tiny model is used for fast inference with reasonable accuracy
- For better accuracy, you can modify the model size in `services/asr_service.py`
