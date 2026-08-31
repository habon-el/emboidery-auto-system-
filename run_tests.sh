#!/usr/bin/env bash
# Full test suite + a batch digitize pass over every testbench/inputs/ file,
# so results are eyeballable in testbench/out/ (Section 8).
set -euo pipefail
cd "$(dirname "$0")"

if [ -d .venv ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo "== pytest =="
python -m pytest tests/ -v

echo
echo "== batch digitize over testbench/inputs/ =="
mkdir -p testbench/out
shopt -s nullglob
for f in testbench/inputs/*.png testbench/inputs/*.jpg testbench/inputs/*.svg; do
    name="$(basename "${f%.*}")"
    echo "--- $name ---"
    python -m src.cli digitize "$f" --fabric twill --out "testbench/out/$name" \
        || echo "  (non-zero exit -- expected for out-of-scope samples)"
done

echo
echo "Done. See testbench/out/ for generated files and *_preview.png images."
