import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from Pipeline.w07_model import LSTMRegressor


DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "oep_regressor.pth"
DEFAULT_ONNX_PATH = Path(__file__).resolve().parent / "models" / "oep_regressor.onnx"


def load_state_dict(model_path: Path) -> dict:
    try:
        return torch.load(model_path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(model_path, map_location="cpu")


def build_model(state_dict: dict) -> LSTMRegressor:
    input_dim = state_dict["lstm1.weight_ih_l0"].shape[1]
    hidden_dim1 = state_dict["lstm1.weight_hh_l0"].shape[1]
    hidden_dim2 = state_dict["lstm2.weight_hh_l0"].shape[1]
    dense_dim = state_dict["dense1.weight"].shape[0]

    model = LSTMRegressor(
        input_dim=input_dim,
        hidden_dim1=hidden_dim1,
        hidden_dim2=hidden_dim2,
        dense_dim=dense_dim,
    )
    model.load_state_dict(state_dict)
    model.eval()
    return model


def validate_onnx(model: LSTMRegressor, onnx_path: Path, sample_input: torch.Tensor) -> None:
    with torch.no_grad():
        torch_output = model(sample_input).cpu().numpy()

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    onnx_output = session.run(None, {input_name: sample_input.cpu().numpy()})[0]

    np.testing.assert_allclose(torch_output, onnx_output, rtol=1e-4, atol=1e-5)


def export_onnx(model_path: Path, onnx_path: Path, opset_version: int) -> None:
    state_dict = load_state_dict(model_path)
    model = build_model(state_dict)
    input_dim = state_dict["lstm1.weight_ih_l0"].shape[1]
    sample_input = torch.randn(2, 1, input_dim, dtype=torch.float32)

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        sample_input,
        onnx_path,
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["features"],
        output_names=["prediction"],
        dynamic_axes={"features": {0: "batch_size"}, "prediction": {0: "batch_size"}},
    )
    validate_onnx(model, onnx_path, sample_input)
    print(f"Exported and validated ONNX model: {onnx_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Optimal Entry Price LSTM model to ONNX.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--onnx-path", type=Path, default=DEFAULT_ONNX_PATH)
    parser.add_argument("--opset-version", type=int, default=17)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export_onnx(args.model_path, args.onnx_path, args.opset_version)
