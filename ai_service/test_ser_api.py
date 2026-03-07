"""
Test script for SER (Speech Emotion Recognition) API
Usage:
    python test_ser_api.py <audio_file>                   # single audio
    python test_ser_api.py <audio1> <audio2> <audio3> ... # multi-chunk (superimpose)
"""

import sys
import os
import requests

API_BASE = "http://localhost:8000/ser"


def test_health():
    """Test the SER health endpoint."""
    try:
        r = requests.get(f"{API_BASE}/health")
        data = r.json()
        print(f"SER Health: {data['status']}")
        if data.get("emotion_labels"):
            print(f"   Labels ({len(data['emotion_labels'])}): {data['emotion_labels']}")
        if data.get("mel_normalisation"):
            n = data["mel_normalisation"]
            print(f"   Mel norm: mean={n['mean']:.4f}, std={n['std']:.4f}")
    except Exception as e:
        print(f"Error: {e}")


def test_predict_single(audio_path: str):
    """Test single-audio emotion prediction."""
    try:
        if not os.path.exists(audio_path):
            print(f"❌ File not found: {audio_path}")
            return

        with open(audio_path, "rb") as f:
            files = {"audio": (os.path.basename(audio_path), f, "audio/wav")}
            print(f"\n🎤 Predicting emotion from: {audio_path}")
            r = requests.post(f"{API_BASE}/predict", files=files)

        if r.status_code == 200:
            data = r.json()
            if data.get("emotion_detected"):
                print(f"   ✅ Emotion: {data['emotion']} ({data['confidence']:.1f}%)")
                print(f"   ⏱  Inference: {data['inference_time_seconds']}s")
                print(f"   📊 Probabilities:")
                for emo, prob in sorted(
                    data["probabilities"].items(), key=lambda x: -x[1]
                ):
                    bar = "█" * int(prob / 2.5)
                    marker = " ◄" if emo == data["emotion"] else ""
                    print(f"      {emo:10s} {prob:5.1f}%  {bar}{marker}")
            else:
                reason = data.get("reason", "unknown")
                print(f"   ⚠️  No emotion detected — {reason}")
        else:
            print(f"   ❌ Error {r.status_code}: {r.text}")

    except Exception as e:
        print(f"Error: {e}")


def test_predict_stream(audio_paths: list, session_id: str = "test"):
    """Test multi-chunk (superimpose) prediction."""
    try:
        files = []
        for path in audio_paths:
            if not os.path.exists(path):
                print(f"⚠️  Skipping missing file: {path}")
                continue
            files.append(
                ("chunks", (os.path.basename(path), open(path, "rb"), "audio/wav"))
            )

        if not files:
            print("❌ No valid audio files provided")
            return

        data = {"session_id": session_id}
        print(f"\n🎬 Predicting with {len(files)} audio chunks (superimpose mode)")
        print(f"   Session: {session_id}")

        r = requests.post(f"{API_BASE}/predict-stream", files=files, data=data)

        # Close file handles
        for _, (_, fh, _) in files:
            fh.close()

        if r.status_code == 200:
            result = r.json()
            if result.get("emotion_detected"):
                print(f"   ✅ Emotion: {result['emotion']} ({result['confidence']:.1f}%)")
                print(f"   🔄 Buffer: {result['buffer_size']}/{result['superimpose_chunks']} chunks")
                print(f"   ⏱  Inference: {result['inference_time_seconds']}s")
                print(f"   📊 Probabilities:")
                for emo, prob in sorted(
                    result["probabilities"].items(), key=lambda x: -x[1]
                ):
                    bar = "█" * int(prob / 2.5)
                    marker = " ◄" if emo == result["emotion"] else ""
                    print(f"      {emo:10s} {prob:5.1f}%  {bar}{marker}")
            else:
                reason = result.get("reason", "unknown")
                print(f"   ⚠️  No emotion detected — {reason}")
        else:
            print(f"   ❌ Error {r.status_code}: {r.text}")

    except Exception as e:
        print(f"Error: {e}")


def test_reset_buffer(session_id: str = "test"):
    """Test buffer reset."""
    try:
        r = requests.post(
            f"{API_BASE}/reset-buffer", data={"session_id": session_id}
        )
        print(f"\n🔄 Reset buffer: {r.json()}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_ser_api.py <audio>                 # single file")
        print("  python test_ser_api.py <a1> <a2> <a3> ...      # multi-chunk")
        sys.exit(1)

    audio_paths = sys.argv[1:]

    print("=" * 55)
    print("  🎙️ SER API Test Suite")
    print("=" * 55)

    print("\n1️⃣  Health check")
    test_health()

    if len(audio_paths) == 1:
        print("\n2️⃣  Single-audio prediction")
        test_predict_single(audio_paths[0])
    else:
        print("\n2️⃣  Single-audio prediction (first file)")
        test_predict_single(audio_paths[0])

        print("\n3️⃣  Multi-chunk superimpose prediction")
        test_predict_stream(audio_paths, session_id="test")

        print("\n4️⃣  Reset buffer")
        test_reset_buffer("test")

    print("\n" + "=" * 55)
    print("  ✅ All tests completed")
    print("=" * 55)
