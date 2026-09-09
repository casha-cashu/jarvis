"""Unit tests for pure ONNX Silero VAD implementation."""

import numpy as np

from jarvis.modules.vad import SileroVAD, VADIteratorWrapper, _find_onnx_model_path


def test_onnx_model_exists():
    path = _find_onnx_model_path()
    assert path is not None
    import os

    assert os.path.isfile(path)


def test_silero_vad_onnx_inference():
    vad = SileroVAD(threshold=0.5, sampling_rate=16000)
    assert vad.is_onnx is True
    assert vad.session is not None

    # Silence chunk
    silence = np.zeros(512, dtype=np.float32)
    p_silence = vad.is_speech(silence)
    assert isinstance(p_silence, float)
    assert 0.0 <= p_silence <= 0.2

    # Speech-like noise
    noise = np.random.uniform(-0.5, 0.5, 512).astype(np.float32)
    p_noise = vad.is_speech(noise)
    assert isinstance(p_noise, float)
    assert 0.0 <= p_noise <= 1.0


def test_vad_iterator_wrapper_onnx():
    vad = SileroVAD(threshold=0.5, sampling_rate=16000)
    wrapper = VADIteratorWrapper(vad, chunk_size=512)

    # Process chunks
    chunk = np.zeros(512, dtype=np.float32)
    res = wrapper.process_chunk(chunk)
    assert isinstance(res, dict)
    assert "speech" in res
    assert "start" in res
    assert "end" in res

    flush_res = wrapper.flush()
    assert isinstance(flush_res, dict)

    wrapper.reset()
    assert wrapper.is_speaking is False
