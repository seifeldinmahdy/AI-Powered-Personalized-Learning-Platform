"""
Test script for ASR API
Usage: python test_asr_api.py <audio_file_path>
"""

import sys
import requests

API_URL = "http://localhost:8000/asr/transcribe"

def test_transcribe(audio_file_path: str, language: str = 'en'):
    """Test the ASR transcription endpoint."""

    try:
        with open(audio_file_path, 'rb') as audio_file:
            files = {
                'audio_file': (audio_file_path, audio_file, 'audio/wav')
            }
            data = {
                'language': language
            }

            print(f"Sending audio file: {audio_file_path}")
            response = requests.post(API_URL, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                print("\n✓ Transcription successful!")
                print(f"Transcription: {result['transcription']}")
                print(f"Language: {result['language']}")
                print(f"Inference time: {result['inference_time_seconds']}s")
            else:
                print(f"\n✗ Error: {response.status_code}")
                print(response.json())

    except FileNotFoundError:
        print(f"Error: File not found: {audio_file_path}")
    except Exception as e:
        print(f"Error: {str(e)}")


def test_health():
    """Test the ASR health endpoint."""
    try:
        response = requests.get("http://localhost:8000/asr/health")
        print(f"ASR Health: {response.json()}")
    except Exception as e:
        print(f"Error checking health: {str(e)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_asr_api.py <audio_file_path> [language]")
        sys.exit(1)

    audio_path = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else 'en'

    print("Testing ASR API health...")
    test_health()
    print("\n" + "="*50 + "\n")

    print("Testing transcription...")
    test_transcribe(audio_path, language)
