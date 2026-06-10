#!/usr/bin/env bash
# =============================================================================
# launch_bias.sh — avvia l'audit nell'ambiente "bias"
#
#   ESEGUILO, non sourcarlo:
#     bash launch_bias.sh            # apre il notebook in Jupyter Lab (default)
#     ./launch_bias.sh notebook      # idem
#     ./launch_bias.sh cli           # run da terminale (MiniLM offline, IT)
#     ./launch_bias.sh cli DE tfidf  # run CLI: paese DE, encoder tfidf
#
#   Override via env: COUNTRY, ENCODER, MODEL_PATH, SEEDS
# =============================================================================

# --- guardia: se viene "sourcato", avvisa e NON toccare la shell dell'utente -
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  echo "NON fare 'source' di questo script: eseguilo con  bash launch_bias.sh"
  return 1 2>/dev/null || exit 1
fi

set -uo pipefail
cd "$(dirname "$0")"

# pausa di cortesia se la finestra rischia di chiudersi su errore (es. doppio click)
trap '[[ $? -ne 0 ]] && { echo; read -rp "Errore. Premi INVIO per chiudere..."; }' EXIT

ENV_NAME="bias"
PY="${ENV_NAME}/bin/python"
JUP="${ENV_NAME}/bin/jupyter"

COUNTRY="${COUNTRY:-IT}"
ENCODER="${ENCODER:-sentence-transformers}"
MODEL_PATH="${MODEL_PATH:-minilm_it}"   # cartella offline; vuota -> scarica da HF
SEEDS="${SEEDS:-10}"

# 1) l'env esiste?
if [[ ! -x "${PY}" ]]; then
  echo "Ambiente '${ENV_NAME}' non trovato in $(pwd)/${ENV_NAME}."
  echo "Crealo prima con:   bash setup.sh"
  exit 1
fi

# 2) bundle modello: se c'e' lo zip ma non la cartella, scompatta
if [[ "${ENCODER}" == "sentence-transformers" && -n "${MODEL_PATH}" \
      && ! -d "${MODEL_PATH}" && -f "${MODEL_PATH}.zip" ]]; then
  echo ">> scompatto ${MODEL_PATH}.zip"
  unzip -q "${MODEL_PATH}.zip"
fi

MODE="${1:-notebook}"
case "${MODE}" in
  notebook|nb)
    if [[ ! -x "${JUP}" ]]; then
      echo "Jupyter non installato nell'env. Aggiungilo con:"
      echo "   ${ENV_NAME}/bin/pip install jupyter ipykernel"
      exit 1
    fi
    echo ">> Jupyter Lab — kernel 'Python (${ENV_NAME})'  (Ctrl-C per fermarlo)"
    "${JUP}" lab bias_ranking_audit.ipynb      # niente 'exec': la shell resta viva
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
    echo "Modo sconosciuto: '${MODE}' (usa: notebook | cli)"; exit 1 ;;
esac
