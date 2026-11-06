#!/bin/sh
# Démarrage d'un conteneur QA Factory SaaS : « moteur » (OpenCode) ou « web » (application).
set -e
cd "${QAF_RACINE:-/srv/qa-factory}"
case "$1" in
  moteur)
    : "${OPENCODE_SERVER_PASSWORD:?OPENCODE_SERVER_PASSWORD obligatoire}"
    : "${QAF_MODELE:?QAF_MODELE obligatoire (ex. openrouter/<fournisseur>/<modèle>)}"
    OPENCODE_CONFIG_CONTENT="$(python3 saas/config_moteur.py)"
    export OPENCODE_CONFIG_CONTENT
    # L'agent n'a pas accès à Squash : on retire ses variables. OpenCode les insère telles quelles dans
    # opencode.json avant de le lire ; un mot de passe contenant " ou \ rendrait le fichier illisible.
    unset SQUASH_TM_API_TOKEN SQUASH_TM_USERNAME SQUASH_TM_PASSWORD SQUASH_TM_BASE_URL SQUASH_MCP_INDEX
    # Ni les secrets de l'application (sessions, comptes, chiffrement des connexions Squash).
    unset QAF_SECRET QAF_CLE_SECRETS QAF_ADMIN_MOT_DE_PASSE
    # Ni les clés des fournisseurs d'IA : le moteur passe par le relais de l'application (app/relais_ia.py).
    unset OPENROUTER_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY
    if [ "${QAF_MODELE#simulation/}" != "$QAF_MODELE" ]; then
      export QAF_FAUX_MODELE_URL="${QAF_FAUX_MODELE_URL:-http://127.0.0.1:4010/v1}"
      python3 saas/dev/faux_modele.py 4010 &
    fi
    exec opencode serve --hostname 0.0.0.0 --port 4096
    ;;
  web)
    : "${QAF_SECRET:?QAF_SECRET obligatoire (chaîne aléatoire longue)}"
    exec python3 -m uvicorn app.main:app --app-dir saas --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
    ;;
  *)
    echo "Usage : demarrer.sh moteur|web" >&2
    exit 2
    ;;
esac
