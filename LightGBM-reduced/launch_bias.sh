#!/usr/bin/env bash
# =============================================================================
# launch_bias.sh — run the audit in the "bias" environment
#
#   RUN it, do NOT source it:
#     bash launch_bias.sh            # open the notebook in Jupyter Lab (default)
#     ./launch_bias.sh notebook      # same
#     ./launch_bias.sh cli           # terminal run (offline MiniLM, IT)
#     ./launch_bias.sh cli DE tfidf  # CLI run: country DE, encoder tfidf
#
#   Overrides via env: COUNTRY, ENCODER, MODEL_PATH, SEEDS
# =============================================================================

# --- guard: if sourced, warn and do NOT touch the user's shell ---------------
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  echo "Do NOT source this script: run it with  bash launch_bias.sh"
  return 1 2>/dev/null || exit 1
fi

set -uo pipefail
cd "$(dirname "$0")"

# keep the window open on error (e.g. when double-clicked)
trap '[[ $? -ne 0 ]] && { echo; read -rp "Error. Press ENTER to close..."; }' EXIT

ENV_NAME="bias"
PY="${ENV_NAME}/bin/python"
JUP="${ENV_NAME}/bin/jupyter"

COUNTRY="${COUNTRY:-IT}"
ENCODER="${ENCODER:-sentence-transformers}"
MODEL_PATH="${MODEL_PATH:-minilm_it}"   # offline folder; empty -> download from HF
SEEDS="${SEEDS:-10}"

# 1) does the env exist?
if [[ ! -x "${PY}" ]]; then
  echo "Environment '${ENV_NAME}' not found in $(pwd)/${ENV_NAME}."
  echo "Create it first with:   bash setup.sh"
  exit 1
fi

# 2) model bundle: if the zip is present but not the folder, unzip it
if [[ "${ENCODER}" == "sentence-transformers" && -n "${MODEL_PATH}" \
      && ! -d "${MODEL_PATH}" && -f "${MODEL_PATH}.zip" ]]; then
  echo ">> unzipping ${MODEL_PATH}.zip"
  unzip -q "${MODEL_PATH}.zip"
fi

MODE="${1:-notebook}"
case "${MODE}" in
  notebook|nb)
    if [[ ! -x "${JUP}" ]]; then
      echo "Jupyter not installed in the env. Add it with:"
      echo "   ${ENV_NAME}/bin/pip install jupyter ipykernel"
      exit 1
    fi
    echo ">> Jupyter Lab — kernel 'Python (${ENV_NAME})'  (Ctrl-C to stop)"
    "${JUP}" lab bias_ranking_audit.ipynb      # no 'exec': the shell stays alive
    ;;
  cli)
    CC="${2:-$COUNTRY}"; EE="${3:-$ENCODER}"
    MP_ARG=()
    [[ "${EE}" == "sentence-transformers" && -n "${MODEL_PATH}" && -d "${MODEL_PATH}" ]] && MP_ARG=(--model-path "${MODEL_PATH}")
    echo ">> CLI | country=${CC} | encoder=${EE} | seeds=${SEEDS} ${MP_ARG[*]:-}"
    "${PY}" bias_ranking_audit.py --db results.db --country "${CC}" \
        --encoder "${EE}" --seeds "${SEEDS}" "${MP_ARG[@]}"
    ;;
  *)
    echo "Unknown mode: '${MODE}' (use: notebook | cli)"; exit 1 ;;
esac
