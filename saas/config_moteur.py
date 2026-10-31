# -*- coding: utf-8 -*-
"""Construit la configuration OpenCode du serveur (variable OPENCODE_CONFIG_CONTENT).

Elle se superpose à opencode.json du dépôt (prioritaire sur lui) : fournisseur OpenRouter,
modèle imposé, aucune écriture dans Squash par l'agent (la publication passe par l'application),
pas d'accès web ni hors du dépôt. Si QAF_MODELE commence par « simulation/ », le faux modèle de
démonstration est ajouté (essais sans clé OpenRouter).
"""
import json
import os
from pathlib import Path

ICI = Path(__file__).resolve().parent


def configuration():
    c = json.loads((ICI / "opencode.serveur.json").read_text(encoding="utf-8"))
    if os.environ.get("QAF_MODELE", "").startswith("simulation/"):
        c["provider"].update(json.loads((ICI / "dev" / "opencode.simulation.json").read_text(encoding="utf-8"))["provider"])
    return c


if __name__ == "__main__":
    print(json.dumps(configuration(), ensure_ascii=False))
