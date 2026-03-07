"""
Test script for FER (Facial Emotion Recognition) API
Usage:
    python test_fer_api.py <image_path>                  # single image
    python test_fer_api.py <img1> <img2> <img3> ...      # multi-frame (superimpose)
"""

import sys
import os
import requests

API_BASE = "http://localhost:8000/fer"


def test_health():
    """Test the FER health endpoint."""
    try:
        r = requests.get(f"{API_BASE}/health")
        data = r.json()
        print(f"FER Health: {data}")
        if data.get("emotion_labels"):
            print(f"   Labels: {data['emotion_labels']}")
    except Exception as e:
        print(f"Error: {e}")


def test_predict_single(image_path: str):
    """Test single-image emotion prediction."""
    try:
        if not os.path.exists(image_path):
            print(f"❌ File not found: {image_path}")
            return

        with open(image_path, "rb") as f:
            files = {"image": (os.path.basename(image_path), f, "image/jpeg")}
            print(f"\n📷 Predicting emotion from: {image_path}")
            r = requests.post(f"{API_BASE}/predict", files=files)

        if r.status_code == 200:
            data = r.json()
            if data["face_detected"]:
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
                print("   ⚠️  No face detected in image")
        else:
            print(f"   ❌ Error {r.status_code}: {r.text}")

    except Exception as e:
        print(f"Error: {e}")


def test_predict_video(image_paths: list, session_id: str = "test"):
    """Test multi-frame (superimpose) prediction."""
    try:
        files = []
        for path in image_paths:
            if not os.path.exists(path):
                print(f"⚠️  Skipping missing file: {path}")
                continue
            files.append(
                ("frames", (os.path.basename(path), open(path, "rb"), "image/jpeg"))
            )

        if not files:
            print("❌ No valid image files provided")
            return

        data = {"session_id": session_id}
        print(f"\n🎬 Predicting with {len(files)} frames (superimpose mode)")
        print(f"   Session: {session_id}")

        r = requests.post(f"{API_BASE}/predict-video", files=files, data=data)

        # Close file handles
        for _, (_, fh, _) in files:
            fh.close()

        if r.status_code == 200:
            result = r.json()
            if result["face_detected"]:
                print(f"   ✅ Emotion: {result['emotion']} ({result['confidence']:.1f}%)")
                print(f"   🔄 Buffer: {result['buffer_size']}/{result['superimpose_frames']} frames")
                print(f"   ⏱  Inference: {result['inference_time_seconds']}s")
                print(f"   📊 Probabilities:")
                for emo, prob in sorted(
                    result["probabilities"].items(), key=lambda x: -x[1]
                ):
                    bar = "█" * int(prob / 2.5)
                    marker = " ◄" if emo == result["emotion"] else ""
                    print(f"      {emo:10s} {prob:5.1f}%  {bar}{marker}")
            else:
                print("   ⚠️  No faces detected in any frame")
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
        print("  python test_fer_api.py <image>             # single image")
        print("  python test_fer_api.py <img1> <img2> ...   # multi-frame")
        sys.exit(1)

    image_paths = sys.argv[1:]

    print("=" * 55)
    print("  😊 FER API Test Suite")
    print("=" * 55)

    print("\n1️⃣  Health check")
    test_health()

    if len(image_paths) == 1:
        print("\n2️⃣  Single-image prediction")
        test_predict_single(image_paths[0])
    else:
        print("\n2️⃣  Single-image prediction (first image)")
        test_predict_single(image_paths[0])

        print("\n3️⃣  Multi-frame superimpose prediction")
        test_predict_video(image_paths, session_id="test")

        print("\n4️⃣  Reset buffer")
        test_reset_buffer("test")

    print("\n" + "=" * 55)
    print("  ✅ All tests completed")
    print("=" * 55)
