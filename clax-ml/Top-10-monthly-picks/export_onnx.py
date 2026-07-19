import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from predict_monthly import Top10LSTM

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "top10_model.pth"
DEFAULT_ONNX_PATH = Path(__file__).resolve().parent / "models" / "top10_model.onnx"
SEQUENCE_LENGTH = 66


def load_state_dict(model_path: Path) -> dict:
    try:
        return torch.load(model_path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(model_path, map_location="cpu")


def build_model(state_dict: dict) -> Top10LSTM:
    input_dim = state_dict["lstm1.weight_ih_l0"].shape[1]
    lstm_hidden = state_dict["lstm1.weight_hh_l0"].shape[1]
    dense_hidden = state_dict["dense1.weight"].shape[0]

    model = Top10LSTM(
        input_dim=input_dim,
        lstm_hidden=lstm_hidden,
        dense_hidden=dense_hidden,
    )
    model.load_state_dict(state_dict)
    model.eval()
    return model


def validate_onnx(model: Top10LSTM, onnx_path: Path, sample_input: torch.Tensor) -> None:
    with torch.no_grad():
        torch_output = model(sample_input).cpu().numpy()

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    onnx_output = session.run(None, {input_name: sample_input.cpu().numpy()})[0]

    np.testing.assert_allclose(torch_output, onnx_output, rtol=1e-4, atol=1e-5)


def export_onnx(model_path: Path, onnx_path: Path, sequence_length: int, opset_version: int) -> None:
    state_dict = load_state_dict(model_path)
    model = build_model(state_dict)
    input_dim = state_dict["lstm1.weight_ih_l0"].shape[1]
    sample_input = torch.randn(2, sequence_length, input_dim, dtype=torch.float32)

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        sample_input,
        onnx_path,
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["features"],
        output_names=["score"],
        dynamic_axes={"features": {0: "batch_size"}, "score": {0: "batch_size"}},
    )
    validate_onnx(model, onnx_path, sample_input)
    print(f"Exported and validated ONNX model: {onnx_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Top 10 monthly picks LSTM model to ONNX.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--onnx-path", type=Path, default=DEFAULT_ONNX_PATH)
    parser.add_argument("--sequence-length", type=int, default=SEQUENCE_LENGTH)
    parser.add_argument("--opset-version", type=int, default=17)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export_onnx(args.model_path, args.onnx_path, args.sequence_length, args.opset_version)
