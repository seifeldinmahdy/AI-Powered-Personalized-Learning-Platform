"""
Test script for TTS API
Usage: python test_tts_api.py [text] [voice]
"""

import sys
import requests
import os

API_BASE = "http://localhost:8000/tts"


def test_health():
    """Test the TTS health endpoint."""
    try:
        r = requests.get(f"{API_BASE}/health")
        print(f"TTS Health: {r.json()}")
    except Exception as e:
        print(f"Error: {e}")


def test_presets():
    """Fetch preset voices and styles."""
    try:
        r = requests.get(f"{API_BASE}/presets")
        data = r.json()
        print("\n📢 Preset voices:")
        for name, voice_id in data["preset_voices"].items():
            print(f"  {name:10s} → {voice_id}")
        print(f"\n🎭 Supported styles: {', '.join(data['supported_styles'])}")
    except Exception as e:
        print(f"Error: {e}")


def test_voices(language: str = "en-US"):
    """List available voices."""
    try:
        r = requests.get(f"{API_BASE}/voices", params={"language": language})
        data = r.json()
        print(f"\n📢 {data['count']} voices for '{language}':")
        for v in data["voices"][:10]:
            print(f"  {v['gender']:6s}  {v['short_name']:45s}  {v['locale']}")
        if data["count"] > 10:
            print(f"  ... and {data['count'] - 10} more")
    except Exception as e:
        print(f"Error: {e}")


def test_synthesize(text: str, voice: str = "en-US-JennyNeural"):
    """Test speech synthesis and save the result."""
    try:
        payload = {"text": text, "voice": voice, "rate": "+0%", "pitch": "+0Hz"}
        print(f"\n🔊 Synthesizing: \"{text[:80]}...\"" if len(text) > 80 else f"\n🔊 Synthesizing: \"{text}\"")
        print(f"   Voice: {voice}")

        r = requests.post(f"{API_BASE}/synthesize", json=payload)

        if r.status_code == 200:
            os.makedirs("tts_test_output", exist_ok=True)
            out = os.path.join("tts_test_output", "test_output.mp3")
            with open(out, "wb") as f:
                f.write(r.content)

            inference_time = r.headers.get("X-TTS-Inference-Time", "?")
            audio_size = r.headers.get("X-TTS-Audio-Size", "?")
            print(f"   ✅ Saved: {out} ({audio_size} bytes, {inference_time}s)")
        else:
            print(f"   ❌ Error {r.status_code}: {r.text}")

    except Exception as e:
        print(f"Error: {e}")


def test_synthesize_json(text: str, voice: str = "en-US-GuyNeural"):
    """Test the metadata-only synthesis endpoint."""
    try:
        payload = {"text": text, "voice": voice}
        r = requests.post(f"{API_BASE}/synthesize-json", json=payload)

        if r.status_code == 200:
            data = r.json()
            print(f"\n📊 Synthesis metadata:")
            for k, v in data.items():
                print(f"   {k}: {v}")
        else:
            print(f"   ❌ Error {r.status_code}: {r.text}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello! This is a test of the text to speech API."
    voice = sys.argv[2] if len(sys.argv) > 2 else "en-US-JennyNeural"

    print("=" * 55)
    print("  🔊 TTS API Test Suite")
    print("=" * 55)

    print("\n1️⃣  Health check")
    test_health()

    print("\n2️⃣  Preset voices & styles")
    test_presets()

    print("\n3️⃣  Available voices")
    test_voices()

    print("\n4️⃣  Synthesize (audio response)")
    test_synthesize(text, voice)

    print("\n5️⃣  Synthesize (JSON metadata)")
    test_synthesize_json(text, voice)

    print("\n" + "=" * 55)
    print("  ✅ All tests completed")
    print("=" * 55)
