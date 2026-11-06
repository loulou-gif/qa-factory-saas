# -*- coding: utf-8 -*-
"""Espace de test commun : copie du dépôt, faux Squash, application web (sans moteur IA).

Le moteur OpenCode n'est démarré que par les tests qui en ont besoin (test_parcours.py), sur le port
réservé ici : l'application lit sa configuration une seule fois, à l'import.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent
DEPOT = ICI.parents[1]
sys.path.insert(0, str(ICI))
from faux_squash import FauxSquash  # noqa: E402

MCP = Path(os.environ.get("SQUASH_MCP_DIR") or DEPOT.parent / "squash-tm-mcp")


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def espace(tmp_path_factory):
    if not (MCP / "dist" / "publish" / "publishBatch.js").exists():
        pytest.skip(f"MCP squash-tm compilé introuvable ({MCP})")
    racine = tmp_path_factory.mktemp("espace") / "qa-factory"
    shutil.copytree(DEPOT, racine, ignore=shutil.ignore_patterns(".git", "donnees", "donnees-demo", "__pycache__", "node_modules",
                                                         "executions", "test-results", "playwright-report", "redactions"))
    for p in (racine / "projets").iterdir():
        if p.name != "saucedemo":
            shutil.rmtree(p)
    subprocess.run(["git", "init", "-q"], cwd=racine, check=True)
    squash = FauxSquash()
    ports = {"modele": port_libre(), "moteur": port_libre()}
    serveur = json.loads((ICI.parent / "opencode.serveur.json").read_text(encoding="utf-8"))
    serveur["provider"].update(json.loads((ICI.parent / "dev" / "opencode.simulation.json").read_text(encoding="utf-8"))["provider"])
    for k in [k for k in os.environ if k.upper().startswith(("SQUASH_TM_", "QAF_CLE_SECRETS"))]:
        os.environ.pop(k)
    os.environ.update({
        "QAF_RACINE": str(racine), "QAF_DONNEES": str(racine / "saas" / "donnees"), "QAF_SECRET": "secret-de-test",
        "OPENCODE_URL": f"http://127.0.0.1:{ports['moteur']}", "OPENCODE_SERVER_PASSWORD": "mdp-moteur",
        "QAF_MODELE": "simulation/demo", "QAF_FAUX_MODELE_URL": f"http://127.0.0.1:{ports['modele']}/v1",
        "OPENCODE_CONFIG_CONTENT": json.dumps(serveur),
        # Sorties des processus enfants en UTF-8 (sous Windows, cp1252 casse la capture de pytest).
        "PYTHONUTF8": "1",
        # Barres obliques : OpenCode insère la variable telle quelle dans opencode.json (des \ le rendraient invalide).
        "SQUASH_MCP_DIR": str(MCP), "SQUASH_MCP_INDEX": (MCP / "dist" / "index.js").as_posix(),
        # Le faux Squash écoute sur 127.0.0.1 : adresses internes autorisées pour les tests.
        "QAF_SQUASH_RESEAU_PRIVE": "true",
        "QAF_ADMIN_IDENTIFIANT": "admin", "QAF_ADMIN_MOT_DE_PASSE": "Provisoire123", "QAF_INTERVALLE_SUIVI_S": "0.5",
    })
    sys.path.insert(0, str(ICI.parent))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield {"client": client, "racine": racine, "squash": squash, "ports": ports}
    squash.arreter()


# ---------------------------------------------------------------- aides

def csrf(client, url="/"):
    h = client.get(url).text
    m = re.search(r'name="csrf" content="([^"]+)"', h) or re.search(r'name="csrf" value="([^"]+)"', h)
    return m.group(1)


def connecter(client, ident, mdp):
    client.post("/deconnexion", data={"csrf": csrf(client, "/connexion")})
    r = client.post("/connexion", data={"identifiant": ident, "mot_de_passe": mdp, "csrf": csrf(client, "/connexion")})
    assert r.status_code in (200, 303)


def jx(client, url, corps=None, page="/"):
    return client.post(url, json=corps or {}, headers={"X-CSRF": csrf(client, page), "Accept": "application/json"})


def regler_squash(client, adresse, mode="compte", identifiant="qa", secret="secret"):
    """Règle la connexion Squash de l'utilisateur connecté, comme dans la page « Squash »."""
    return client.post("/parametres/squash", data={"adresse": adresse, "mode": mode, "identifiant": identifiant, "secret": secret,
                                                    "csrf": csrf(client, "/parametres/squash")})
