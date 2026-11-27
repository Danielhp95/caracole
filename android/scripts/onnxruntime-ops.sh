#!/usr/bin/env bash
# The ops the phone's ONNX Runtime keeps the kernels of, android/ml/onnxruntime-ops.config, made again from the graphs:
#
#   android/scripts/onnxruntime-ops.sh            write the config
#   android/scripts/onnxruntime-ops.sh --check    exit 1 unless every op the graphs need is in the committed config
#
# The graphs are `nix build .#chord-models`' ($CARACOLE_CHORD_MODELS, else the ./android#ml shell's). Each is read as it
# is and as ONNX Runtime 1.27.1 (nixpkgs' python3Packages.onnxruntime at android/flake.nix's pin, the phone's release)
# optimizes it at ORT_ENABLE_ALL and ORT_ENABLE_EXTENDED, twice: on this machine's x86_64 (./android#onnxruntime-ops-
# python), and on aarch64 under qemu-user (./android#onnxruntime-ops-aarch64, cache.nixos.org's aarch64 build), whose
# fusions are the phone's CPU's. ORT's own tools/python (its source's, ./android#onnxruntime-android.src) read the ops.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
repo="$(dirname "$android")"
check=0
[ "${1-}" = --check ] && check=1
config="$android/ml/onnxruntime-ops.config"

cd "$repo"
models="${CARACOLE_CHORD_MODELS:-$(nix develop ./android#ml -c printenv CARACOLE_CHORD_MODELS)}"
for g in btc-graph.onnx beat_this-final0.onnx beat_this-final0-fp16.onnx; do
    [ -f "$models/$g" ] || { echo "onnxruntime-ops.sh: no $g in '$models'" >&2; exit 2; }
done
python="$(nix build --no-link --print-out-paths ./android#onnxruntime-ops-python)/bin/python3"
aarch64="$(nix build --no-link --print-out-paths ./android#onnxruntime-ops-aarch64)/bin/onnxruntime-ops-aarch64"
tools="$(nix build --no-link --print-out-paths ./android#onnxruntime-android.src)/tools/python"

work="$(mktemp -d "${TMPDIR:-/tmp}/caracole-ort-ops-XXXXXX")"
trap 'rm -rf "$work"' EXIT
# Copies, writable: the optimized graphs' external data go beside them.
mkdir -p "$work/models"
cp "$models"/*.onnx "$models"/*.pt "$work/models/"
chmod u+w "$work/models"/*
"$python" -B "$here/onnxruntime_ops.py" optimize "$work/models" "$work/x86_64"
"$aarch64" "$here/onnxruntime_ops.py" optimize "$work/models" "$work/aarch64"
"$python" -B "$here/onnxruntime_ops.py" config "$tools" "$work/ops.config" "$work/models" "$work/x86_64" "$work/aarch64"

if [ "$check" = 0 ]; then
    cp "$work/ops.config" "$config"
    echo "onnxruntime-ops.sh: wrote $config"
    exit 0
fi
# Every op of the graphs, plain and optimized on either CPU, in the committed config.
"$python" -B - "$work/ops.config" "$config" <<'EOF'
import sys
def ops(path):
    found = set()
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            domain, opset, names = line.strip().split(";")
            found |= {(domain, int(opset), name) for name in names.split(",")}
    return found
needed, kept = ops(sys.argv[1]), ops(sys.argv[2])
missing = sorted(needed - kept)
for domain, opset, name in missing:
    print(f"onnxruntime-ops.sh: {domain} {opset} {name} is needed and not in {sys.argv[2]}")
print(f"onnxruntime-ops.sh: {len(needed)} ops needed, {len(kept)} kept, {len(missing)} missing")
sys.exit(1 if missing else 0)
EOF
