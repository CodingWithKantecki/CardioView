"""Frozen HuBERT-ECG features for prepared windows. Needs the ML venv (tools/requirements-ml.txt)."""
from __future__ import annotations

import numpy as np
import torch

MODEL = "Edoardo-Coppola/hubert-ecg-small"
LAYERS = (2, 4, 6, 8)   # transformer layers kept; the head picks from these


class Encoder:
    def __init__(self, model: str = MODEL, layers=LAYERS):
        import hubert_ecg  # noqa: F401  registers HuBERTECG with AutoModel
        from transformers import AutoModel

        self.layers = tuple(layers)
        self.model = AutoModel.from_pretrained(model).eval()
        for p in self.model.parameters():
            p.requires_grad_(False)
        self._taps: dict[int, torch.Tensor] = {}
        for k in self.layers:   # this transformers version drops output_hidden_states, so tap the layers
            self.model.encoder.layers[k - 1].register_forward_hook(self._tap(k))

    def _tap(self, k):
        def hook(_module, _args, out):
            self._taps[k] = out[0] if isinstance(out, tuple) else out
        return hook

    @torch.no_grad()
    def features(self, x: np.ndarray, batch: int = 32) -> np.ndarray:
        """(N, 2, 6000) prepared windows to (N, 2, layers, 1024): per 5 s half and per layer, the mean
        and the spread over time of the 512 features."""
        n, halves = x.shape[:2]
        flat = torch.from_numpy(np.ascontiguousarray(x.reshape(n * halves, -1)))
        out = []
        for i in range(0, len(flat), batch):
            self.model(flat[i:i + batch])
            out.append(torch.stack([torch.cat([self._taps[k].mean(1), self._taps[k].std(1)], 1)
                                    for k in self.layers], 1).numpy())
        return np.concatenate(out).reshape(n, halves, len(self.layers), -1)
