#!/usr/bin/env bash
# =============================================================================
# Setup ambiente "bias" — versione PIENA (MiniLM via sentence-transformers)
# Da eseguire IN LOCALE:  bash setup.sh
# =============================================================================
set -euo pipefail

ENV_NAME="bias"

# --- Scegli la variante torch in base alla tua macchina -----------------------
#   "cu124" -> GPU NVIDIA con CUDA 12.4 (la riga che usi tu)
#   "cpu"   -> nessuna GPU
#   "auto"  -> lascia decidere a pip (di default su Linux scarica il build CUDA,
#              pesante ~2.5GB; su macOS/Windows il build adatto)
TORCH_VARIANT="${TORCH_VARIANT:-cu124}"

echo ">> Creo il virtualenv '${ENV_NAME}'"
python3 -m venv "${ENV_NAME}"
PY="${ENV_NAME}/bin/python"
PIP="${ENV_NAME}/bin/pip"

"${PIP}" install --upgrade pip wheel

echo ">> Core: learning-to-rank + interpretazione + notebook"
"${PIP}" install lightgbm shap scikit-learn pandas numpy matplotlib jupyter ipykernel nbformat

echo ">> torch (variante: ${TORCH_VARIANT})"
case "${TORCH_VARIANT}" in
  cu124) "${PIP}" install torch --index-url https://download.pytorch.org/whl/cu124 ;;
  cpu)   "${PIP}" install torch --index-url https://download.pytorch.org/whl/cpu   ;;
  auto)  "${PIP}" install torch ;;
  *) echo "TORCH_VARIANT sconosciuto: ${TORCH_VARIANT} (usa cu124|cpu|auto)"; exit 1 ;;
esac

echo ">> Encoder semantico pieno (MiniLM)"
"${PIP}" install sentence-transformers

echo ">> Alternativa leggera senza torch (opzionale)"
"${PIP}" install model2vec

echo ">> Registro il kernel Jupyter 'bias'"
"${PY}" -m ipykernel install --user --name "${ENV_NAME}" --display-name "Python (${ENV_NAME})"

echo ">> Verifica"
"${PY}" - <<'PYCHK'
import torch, sentence_transformers as st, lightgbm, shap
print("torch", torch.__version__, "| CUDA:", torch.cuda.is_available(), "| ST", st.__version__)
print("lightgbm", lightgbm.__version__, "| shap", shap.__version__)
PYCHK

echo ">> Test GPU rapido"
"${PY}" - <<'PYGPU'
import torch
print("  CUDA disponibile:", torch.cuda.is_available(), "| build:", torch.version.cuda)
if torch.cuda.is_available():
    print("  GPU:", torch.cuda.get_device_name(0))
PYGPU

cat <<EOF

============================================================
  Ambiente '${ENV_NAME}' pronto.
  Avvia il notebook con:
      ${ENV_NAME}/bin/jupyter lab bias_ranking_audit.ipynb
  (oppure apri il notebook e seleziona il kernel "Python (${ENV_NAME})")

  ENCODER nel notebook:
    "sentence-transformers"  -> MiniLM pieno.
       * ONLINE  : lascia ST_LOCAL_PATH="" -> scarica ~470 MB da Hugging Face.
       * OFFLINE : scompatta il bundle ->  unzip minilm_it.zip
                   e imposta  ST_LOCAL_PATH="minilm_it"  (nessun download).

  Da CLI equivalente:
      ${ENV_NAME}/bin/python bias_ranking_audit.py --country IT \\
          --encoder sentence-transformers --model-path minilm_it

  Variante torch usata: ${TORCH_VARIANT}  (cambiala con: TORCH_VARIANT=cpu bash setup.sh)
============================================================
EOF
