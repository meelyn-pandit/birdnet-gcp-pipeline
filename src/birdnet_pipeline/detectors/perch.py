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


def class_names(model) -> list[str]:
    return list(model.class_list["labels"].classes)


def all_outputs(model, audio_path, windows):
    """(logits for ALL classes [n_windows, n_classes], embeddings [n_windows, 1536])."""
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
    logits = np.asarray(out.logits["label"]).reshape(len(windows), -1)
    emb = np.asarray(out.embeddings).reshape(len(windows), -1)
    return logits, emb


def window_outputs(model, audio_path, windows, class_idx: int):
    """(logits for one class, embeddings) for each (w0, w1) window."""
    logits, emb = all_outputs(model, audio_path, windows)
    return logits[:, class_idx], emb


def top_classes(logits, class_idx, top_k: int = 5, floor: float = 2.0):
    """Per window, the top_k classes among class_idx with logit >= floor: [(window, class, logit)]."""
    class_idx = np.asarray(class_idx)
    sub = logits[:, class_idx]
    out = []
    for w in range(sub.shape[0]):
        order = np.argsort(-sub[w])[:top_k]
        out.extend((w, int(class_idx[j]), float(sub[w, j])) for j in order if sub[w, j] >= floor)
    return out


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
