# -*- coding: utf-8 -*-
"""Construit la configuration OpenCode du serveur (variable OPENCODE_CONFIG_CONTENT).

Elle se superpose à opencode.json du dépôt (prioritaire sur lui) : modèle imposé, aucune écriture dans
Squash par l'agent (la publication passe par l'application), pas d'accès web ni hors du dépôt.

Fournisseurs d'IA (OpenRouter, Anthropic, OpenAI) : appelés à travers le relais de l'application web
(app/relais_ia.py, QAF_RELAIS_IA, par défaut http://web:8000/ia). Le moteur ne reçoit qu'un jeton interne,
jamais la clé d'API : elle est ajoutée par l'application (Paramètres > Modèles d'IA, ou variables du serveur).

Si QAF_MODELE commence par « simulation/ », le faux modèle de démonstration est ajouté (essais sans clé).
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

ICI = Path(__file__).resolve().parent


def jeton_relais() -> str:
    """Même calcul que app/relais_ia.py."""
    j = os.environ.get("QAF_JETON_RELAIS", "").strip()
    if j:
        return j
    mdp = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    return hmac.new(mdp.encode(), b"qaf-relais-ia", hashlib.sha256).hexdigest() if mdp else ""


def configuration(modele: str = None) -> dict:
    modele = os.environ.get("QAF_MODELE", "") if modele is None else modele
    c = json.loads((ICI / "opencode.serveur.json").read_text(encoding="utf-8"))
    relais = os.environ.get("QAF_RELAIS_IA", "http://web:8000/ia").rstrip("/")
    jeton = jeton_relais()
    for nom, p in c["provider"].items():
        o = p.get("options") or {}
        if str(o.get("baseURL", "")).startswith("relais/"):
            o["baseURL"] = f"{relais}/{nom}"
            o["apiKey"] = jeton
    if modele.startswith("simulation/"):
        c["provider"].update(json.loads((ICI / "dev" / "opencode.simulation.json").read_text(encoding="utf-8"))["provider"])
    return c


if __name__ == "__main__":
    print(json.dumps(configuration(), ensure_ascii=False))
