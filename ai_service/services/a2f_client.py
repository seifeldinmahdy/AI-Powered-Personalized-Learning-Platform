"""
Audio2Face-3D gRPC Client — drives NVIDIA Audio2Face NIM for blendshape animation.

Bidirectional-streaming client that sends WAV audio to the A2F NIM
and collects per-frame ARKit blendshape weights in return.

NEVER raises exceptions — always returns None on failure so the
caller can fall back to pre-defined viseme sequences.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

import grpc
from nvidia_ace.audio_pb2 import AudioHeader
from nvidia_ace.animation_pb2 import AnimationData
from nvidia_audio2face_3d.audio2face_pb2_grpc import A2FControllerServiceStub
from nvidia_audio2face_3d.messages_pb2 import (
    AudioWithEmotionStream,
    AudioWithEmotionStreamHeader,
    AudioWithEmotion,
)

logger = logging.getLogger(__name__)

# ── .env loading (Windows may produce UTF-16 LE .env files) ──────
_this_dir = Path(__file__).resolve().parent
for _candidate in [
    _this_dir / ".env",
    _this_dir.parent / ".env",
    _this_dir.parent.parent / ".env",
]:
    if _candidate.exists():
        try:
            load_dotenv(_candidate, encoding="utf-16")
        except Exception:
            load_dotenv(_candidate)
        break
else:
    load_dotenv()

A2F_GRPC_HOST = os.getenv("A2F_GRPC_HOST", "localhost")
A2F_GRPC_PORT = int(os.getenv("A2F_GRPC_PORT", "52000"))
A2F_CHUNK_SIZE = 8192  # bytes per audio chunk


def _audio_stream_generator(wav_path: str):
    """Yield AudioWithEmotionStream messages for the A2F bidirectional RPC.

    Protocol:
    1. First message: header with audio metadata (16 kHz, mono, 16-bit PCM)
    2. Subsequent messages: raw audio chunks
    3. Final message: end-of-audio signal
    """
    # 1 — Header
    audio_header = AudioHeader(
        audio_format=AudioHeader.AudioFormat.AUDIO_FORMAT_PCM,
        channel_count=1,
        samples_per_second=16000,
        bits_per_sample=16,
    )
    header_msg = AudioWithEmotionStreamHeader(audio_header=audio_header)
    yield AudioWithEmotionStream(audio_stream_header=header_msg)

    # 2 — Audio chunks (skip 44-byte WAV header)
    with open(wav_path, "rb") as f:
        f.seek(44)  # skip RIFF/WAV header
        while True:
            chunk = f.read(A2F_CHUNK_SIZE)
            if not chunk:
                break
            audio_data = AudioWithEmotion(audio_buffer=chunk)
            yield AudioWithEmotionStream(audio_with_emotion=audio_data)

    # 3 — End-of-audio
    yield AudioWithEmotionStream(end_of_audio=True)


def get_blendshapes(wav_path: str) -> dict | None:
    """Send WAV audio to Audio2Face-3D NIM and return blendshape frames.

    Parameters
    ----------
    wav_path : str
        Path to a 16 kHz mono 16-bit PCM WAV file.

    Returns
    -------
    dict | None
        On success: ``{"blendshape_names": [...], "frames": [[...], ...]}``
        On any failure: ``None`` (caller should use fallback viseme animation).
    """
    target = f"{A2F_GRPC_HOST}:{A2F_GRPC_PORT}"

    try:
        channel = grpc.insecure_channel(target)
        stub = A2FControllerServiceStub(channel)

        request_iter = _audio_stream_generator(wav_path)
        responses = stub.ProcessAudioStream(request_iter)

        blendshape_names: list[str] = []
        frames: list[list[float]] = []

        for response in responses:
            # Extract header with blendshape names
            if response.HasField("animation_data_stream_header"):
                header = response.animation_data_stream_header
                if header.HasField("skel_animation_header"):
                    blendshape_names = list(
                        header.skel_animation_header.blend_shapes
                    )
                    logger.info(
                        "A2F header received — %d blendshapes: %s",
                        len(blendshape_names),
                        blendshape_names[:5],
                    )

            # Extract animation data frames
            if response.HasField("animation_data"):
                anim: AnimationData = response.animation_data
                if anim.HasField("skel_animation"):
                    for bs_weight in anim.skel_animation.blend_shape_weights:
                        frames.append(list(bs_weight.values))

        channel.close()

        if not blendshape_names or not frames:
            logger.warning(
                "A2F returned empty data — names=%d frames=%d",
                len(blendshape_names),
                len(frames),
            )
            return None

        logger.info(
            "A2F blendshapes extracted — %d names × %d frames",
            len(blendshape_names),
            len(frames),
        )
        return {
            "blendshape_names": blendshape_names,
            "frames": frames,
        }

    except grpc.RpcError as e:
        logger.warning("A2F gRPC error (falling back to visemes): %s", e)
        return None
    except FileNotFoundError:
        logger.warning("A2F WAV file not found: %s", wav_path)
        return None
    except Exception as e:
        logger.warning("A2F unexpected error (falling back to visemes): %s", e)
        return None
