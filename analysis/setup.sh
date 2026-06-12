#!/usr/bin/env bash
# =============================================================================
# Set up the "bias" environment — FULL version (MiniLM via sentence-transformers)
# Run LOCALLY:  bash setup.sh
# =============================================================================
set -euo pipefail

ENV_NAME="bias"

# --- Pick the torch variant for your machine ---------------------------------
#   "cu124" -> NVIDIA GPU with CUDA 12.4 (the one you use)
#   "cpu"   -> no GPU
#   "auto"  -> let pip decide (on Linux it pulls the CUDA build by default,
#              heavy ~2.5GB; on macOS/Windows the appropriate build)
TORCH_VARIANT="${TORCH_VARIANT:-cu124}"

echo ">> Creating virtualenv '${ENV_NAME}'"
python3 -m venv "${ENV_NAME}"
PY="${ENV_NAME}/bin/python"
PIP="${ENV_NAME}/bin/pip"

"${PIP}" install --upgrade pip wheel

echo ">> Core: learning-to-rank + interpretation + notebook"
"${PIP}" install lightgbm shap scikit-learn pandas numpy matplotlib jupyter ipykernel nbformat

echo ">> torch (variant: ${TORCH_VARIANT})"
case "${TORCH_VARIANT}" in
  cu124) "${PIP}" install torch --index-url https://download.pytorch.org/whl/cu124 ;;
  cpu)   "${PIP}" install torch --index-url https://download.pytorch.org/whl/cpu   ;;
  auto)  "${PIP}" install torch ;;
  *) echo "Unknown TORCH_VARIANT: ${TORCH_VARIANT} (use cu124|cpu|auto)"; exit 1 ;;
esac

echo ">> Full semantic encoder (MiniLM)"
"${PIP}" install sentence-transformers

echo ">> Lightweight alternative without torch (optional)"
"${PIP}" install model2vec

echo ">> Registering the Jupyter kernel 'bias'"
"${PY}" -m ipykernel install --user --name "${ENV_NAME}" --display-name "Python (${ENV_NAME})"

echo ">> Verification"
"${PY}" - <<'PYCHK'
import torch, sentence_transformers as st, lightgbm, shap
print("torch", torch.__version__, "| CUDA:", torch.cuda.is_available(), "| ST", st.__version__)
print("lightgbm", lightgbm.__version__, "| shap", shap.__version__)
PYCHK

echo ">> GPU quick test"
"${PY}" - <<'PYGPU'
import torch
print("  CUDA available:", torch.cuda.is_available(), "| build:", torch.version.cuda)
if torch.cuda.is_available():
    print("  GPU:", torch.cuda.get_device_name(0))
PYGPU

cat <<EOF

============================================================
  Environment '${ENV_NAME}' is ready.
  Launch the notebook with:
      ${ENV_NAME}/bin/jupyter lab bias_ranking_audit.ipynb
  (or open the notebook and select the kernel "Python (${ENV_NAME})")

  ENCODER nel notebook:
    "sentence-transformers"  -> full MiniLM.
       * ONLINE  : leave ST_LOCAL_PATH="" -> downloads ~470 MB from Hugging Face.
       * OFFLINE : unzip the bundle ->  unzip minilm_it.zip
                   and set  ST_LOCAL_PATH="minilm_it"  (no download).

  Equivalent CLI:
      ${ENV_NAME}/bin/python bias_ranking_audit.py --country IT \\
          --encoder sentence-transformers --model-path minilm_it

  torch variant used: ${TORCH_VARIANT}  (change it with: TORCH_VARIANT=cpu bash setup.sh)
============================================================
EOF
