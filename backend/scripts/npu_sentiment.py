"""
Run a small sentiment model on Intel NPU via OpenVINO.

This is intentionally host-side and separate from the Docker stack.
It gives the repo one concrete NPU-backed workload without changing the
main Ollama/Neo4j runtime path.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import openvino as ov
from transformers import AutoTokenizer


DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "openvino-distilbert-sst2"
)
DEFAULT_MAX_LENGTH = 128
LABELS = ["negative", "positive"]


class NPUSentimentClassifier:
    def __init__(
        self,
        model_dir: Path = DEFAULT_MODEL_DIR,
        device: str = "NPU",
        max_length: int = DEFAULT_MAX_LENGTH,
    ):
        self.model_dir = Path(model_dir)
        self.device = device
        self.max_length = max_length

        model_path = self.model_dir / "openvino_model.xml"
        if not model_path.exists():
            raise FileNotFoundError(
                f"OpenVINO model not found at {model_path}. "
                "Export the model before running this script."
            )

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))

        core = ov.Core()
        model = core.read_model(str(model_path))
        model.reshape({inp.any_name: [1, self.max_length] for inp in model.inputs})
        self.compiled_model = core.compile_model(model, self.device)

    def classify(self, text: str) -> dict:
        encoded = self.tokenizer(
            text,
            return_tensors="np",
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
        )

        outputs = self.compiled_model(
            {
                "input_ids": encoded["input_ids"].astype(np.int64),
                "attention_mask": encoded["attention_mask"].astype(np.int64),
            }
        )

        logits = np.array(next(iter(outputs.values()))[0], dtype=np.float32)
        probabilities = _softmax(logits)
        label_index = int(np.argmax(probabilities))

        return {
            "label": LABELS[label_index],
            "score": float(probabilities[label_index]),
            "probabilities": {
                label: float(probabilities[index])
                for index, label in enumerate(LABELS)
            },
            "device": self.device,
            "max_length": self.max_length,
        }


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp_values = np.exp(shifted)
    return exp_values / np.sum(exp_values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sentiment inference on Intel NPU")
    parser.add_argument("text", help="Text to classify")
    parser.add_argument(
        "--model-dir",
        default=str(DEFAULT_MODEL_DIR),
        help="Path to exported OpenVINO model directory",
    )
    parser.add_argument(
        "--device",
        default="NPU",
        help="OpenVINO device to use, for example NPU, GPU, or CPU",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=DEFAULT_MAX_LENGTH,
        help="Fixed sequence length used when compiling the model",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    classifier = NPUSentimentClassifier(
        model_dir=Path(args.model_dir),
        device=args.device,
        max_length=args.max_length,
    )
    result = classifier.classify(args.text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()