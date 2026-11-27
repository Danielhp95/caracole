"""The ops the phone's ONNX Runtime keeps the kernels of (ml/onnxruntime-ops.config), from the graphs themselves.

Run by onnxruntime-ops.sh, never by hand:

    python3 onnxruntime_ops.py optimize MODELS OUT    ONNX Runtime 1.27.1's own optimizer over each graph of MODELS,
                                                     at ORT_ENABLE_ALL and ORT_ENABLE_EXTENDED, each saved in OUT
    python3 onnxruntime_ops.py config TOOLS OUT DIR...
                                                     every op of every graph in each DIR, plain and optimized, read by
                                                     ORT's own tools/python (TOOLS: its source's), as OUT, the config
                                                     reduce_op_kernels.py takes

The optimizer is run on each machine whose optimizations differ: this one's x86_64 and, under qemu-user, aarch64, the
phone's (its NCHWc and fused kernels are the CPU's). Standard library and ORT's own modules alone.
"""

import pathlib
import sys

ORT_VERSION = "1.27.1"
GRAPHS = ("btc-graph.onnx", "beat_this-final0.onnx", "beat_this-final0-fp16.onnx")
HEADER = """# The ops whose kernels the phone's ONNX Runtime keeps (android/scripts/build-onnxruntime.sh,
# onnxruntime_REDUCED_OPS_BUILD), made by android/scripts/onnxruntime-ops.sh from `nix build .#chord-models`' three
# graphs (btc-graph.onnx, beat_this-final0.onnx, beat_this-final0-fp16.onnx) and the same graphs as ONNX Runtime 1.27.1
# optimizes them on the CPU, ORT_ENABLE_ALL and ORT_ENABLE_EXTENDED, on x86_64 and on aarch64 (under qemu-user), so
# that the fused ops its optimizers make (com.microsoft's, NCHWc's) keep their kernels. Made again when the graphs
# change; `onnxruntime-ops.sh --check` holds this file to them.
"""


def optimize(models: pathlib.Path, out: pathlib.Path) -> None:
    import onnxruntime as ort

    # The phone's release: another's optimizer may fuse otherwise, and its list would be the wrong one.
    if ort.__version__ != ORT_VERSION:
        sys.exit(f"onnxruntime_ops.py: onnxruntime {ort.__version__} here, not {ORT_VERSION}, the phone's")
    out.mkdir(parents=True, exist_ok=True)
    levels = {"all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL, "ext": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED}
    for name in GRAPHS:
        for level, value in levels.items():
            options = ort.SessionOptions()
            options.graph_optimization_level = value
            options.optimized_model_filepath = str(out / f"{level}-{name}")
            options.add_session_config_entry(
                "session.optimized_model_external_initializers_file_name", f"{level}-{name}.data")
            ort.InferenceSession(str(models / name), options, providers=["CPUExecutionProvider"])
    print(f"optimized by onnxruntime {ort.__version__}: {len(GRAPHS) * len(levels)} graphs in {out}")


def config(tools: pathlib.Path, out: pathlib.Path, dirs: list[pathlib.Path]) -> None:
    sys.path.insert(0, str(tools))
    from create_reduced_build_config import _extract_ops_from_onnx_model

    files = sorted(p for d in dirs for p in d.iterdir() if p.suffix == ".onnx")
    required = _extract_ops_from_onnx_model(files)
    lines = [HEADER]
    for domain in sorted(required):
        for opset in sorted(required[domain]):
            ops = required[domain][opset]
            if ops:
                lines.append(f"{domain};{opset};{','.join(sorted(ops))}\n")
    out.write_text("".join(lines), encoding="utf-8")
    print(f"{len(files)} graphs read into {out}")


if __name__ == "__main__":
    step, *args = sys.argv[1:]
    if step == "optimize":
        optimize(pathlib.Path(args[0]), pathlib.Path(args[1]))
    elif step == "config":
        config(pathlib.Path(args[0]), pathlib.Path(args[1]), [pathlib.Path(a) for a in args[2:]])
    else:
        sys.exit(f"onnxruntime_ops.py: optimize or config, not {step}")
