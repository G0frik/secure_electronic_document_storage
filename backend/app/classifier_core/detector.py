"""Prompt-injection detectors (defense D4): the highest injection probability over 512-token windows.

Used by the service (CLASSIFIER_DEFENSES contains D4) and by research.detect. Runs on CPU; the
model is downloaded from Hugging Face on first use (Prompt Guard 2 is gated: HF token required).
"""

from __future__ import annotations

# name -> (HF model id, label that means injection)
DETECTORS = {
    "pg2": ("meta-llama/Llama-Prompt-Guard-2-86M", "LABEL_1"),
    "protectai": ("protectai/deberta-v3-base-prompt-injection-v2", "INJECTION"),
}
WINDOW = 512
OVERLAP = 64


def windows(ids: list[int], size: int, overlap: int) -> list[list[int]]:
    """Token windows of at most `size` covering every token; an empty text is one empty window."""
    step = size - overlap
    return [ids[i : i + size] for i in range(0, max(1, len(ids) - overlap), step)]


class Detector:
    def __init__(self, name: str) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.model_id, label = DETECTORS[name]
        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id).eval()
        self.index = self.model.config.label2id[label]
        self.torch = torch

    def score(self, text: str) -> tuple[float, int]:
        """Max injection probability over the windows, and the number of windows."""
        room = WINDOW - self.tok.num_special_tokens_to_add()
        ids = self.tok(text, add_special_tokens=False)["input_ids"]
        best, chunks = 0.0, windows(ids, room, OVERLAP)
        for i in range(0, len(chunks), 16):
            batch = [self.tok.build_inputs_with_special_tokens(c) for c in chunks[i : i + 16]]
            enc = self.tok.pad({"input_ids": batch}, return_tensors="pt")
            with self.torch.no_grad():
                probs = self.model(**enc).logits.softmax(-1)[:, self.index]
            best = max(best, float(probs.max()))
        return best, len(chunks)
