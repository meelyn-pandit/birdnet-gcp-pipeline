"""Run Google's Perch v2 classifier on analysis windows, with caching.

Perch listens to 5-second windows at 32 kHz. Each 3-second analysis window
is scored with the 5 s of audio centred on it, so Perch outputs line up
with BirdNET windows and annotations. The model (~390 MB) is downloaded
from Kaggle on first use and cached by kagglehub.
"""
from pathlib import Path

import numpy as np

MODEL_NAME = "perch_v2_cpu"
SAMPLE_RATE = 32000
CONTEXT_S = 5.0


def load_model(name: str = MODEL_NAME):
    from perch_hoplite.zoo import model_configs
    return model_configs.load_model_by_name(name)


def class_index(model, scientific: str) -> int:
    classes = list(model.class_list["labels"].classes)
    if scientific not in classes:
        raise KeyError(f"{scientific!r} is not a Perch class")
    return classes.index(scientific)


def load_audio(path) -> np.ndarray:
    import soundfile as sf
    from scipy import signal

    x, sr = sf.read(str(path))
    if x.ndim > 1:
        x = x.mean(axis=1)
    return signal.resample_poly(x, SAMPLE_RATE, sr).astype(np.float32)


def window_outputs(model, audio_path, windows, class_idx: int):
    """(logits for one class, embeddings) for each (w0, w1) window."""
    x = load_audio(audio_path)
    dur = len(x) / SAMPLE_RATE
    n_ctx = int(CONTEXT_S * SAMPLE_RATE)
    frames = []
    for w0, w1 in windows:
        c = (w0 + w1) / 2
        s0 = int(np.clip(c - CONTEXT_S / 2, 0, max(0.0, dur - CONTEXT_S)) * SAMPLE_RATE)
        frame = x[s0:s0 + n_ctx]
        frames.append(np.pad(frame, (0, n_ctx - len(frame))))
    out = model.batch_embed(np.stack(frames)[:, None, :])
    logits = np.asarray(out.logits["label"]).reshape(len(windows), -1)[:, class_idx]
    emb = np.asarray(out.embeddings).reshape(len(windows), -1)
    return logits, emb


class CachedPerch:
    """Perch outputs per recording, cached as <cache>/<recording>.npz."""

    def __init__(self, cache_dir, scientific: str):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.scientific = scientific
        self._model = None
        self._idx = None

    def outputs(self, recording: str, audio_path, windows):
        cf = self.cache / f"{recording}.npz"
        if cf.exists():
            z = np.load(cf)
            if str(z["sci"]) == self.scientific and len(z["logits"]) == len(windows):
                return z["logits"], z["emb"]
        if self._model is None:
            self._model = load_model()
            self._idx = class_index(self._model, self.scientific)
        logits, emb = window_outputs(self._model, audio_path, windows, self._idx)
        np.savez(cf, logits=logits, emb=emb, sci=self.scientific)
        return logits, emb
