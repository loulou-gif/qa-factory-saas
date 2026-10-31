# -*- coding: utf-8 -*-
"""Parcours complet du temps A dans l'application web, avec le vrai OpenCode (faux modèle) et un faux Squash.

Lancement : cd saas && python -m pytest -q tests
Prérequis : opencode, node, python avec fastapi/httpx/openpyxl/python-docx, et le MCP squash-tm compilé
(SQUASH_MCP_DIR, défaut ../squash-tm-mcp à côté du dépôt).
"""
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
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


def attendre(cond, delai=120, pas=0.5):
    fin = time.time() + delai
    while time.time() < fin:
        r = cond()
        if r:
            return r
        time.sleep(pas)
    raise AssertionError("délai dépassé")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    if not (MCP / "dist" / "publish" / "publishBatch.js").exists():
        pytest.skip(f"MCP squash-tm compilé introuvable ({MCP})")
    racine = tmp_path_factory.mktemp("espace") / "qa-factory"
    shutil.copytree(DEPOT, racine, ignore=shutil.ignore_patterns(".git", "donnees", "__pycache__", "node_modules"))
    for p in (racine / "projets").iterdir():
        if p.name != "saucedemo":
            shutil.rmtree(p)
    subprocess.run(["git", "init", "-q"], cwd=racine, check=True)
    squash = FauxSquash()
    p_modele, p_oc = port_libre(), port_libre()
    modele = subprocess.Popen([sys.executable, str(ICI.parent / "dev" / "faux_modele.py"), str(p_modele)])
    serveur = json.loads((ICI.parent / "opencode.serveur.json").read_text(encoding="utf-8"))
    serveur["provider"].update(json.loads((ICI.parent / "dev" / "opencode.simulation.json").read_text(encoding="utf-8"))["provider"])
    variables = {
        "QAF_RACINE": str(racine), "QAF_DONNEES": str(racine / "saas" / "donnees"), "QAF_SECRET": "secret-de-test",
        "OPENCODE_URL": f"http://127.0.0.1:{p_oc}", "OPENCODE_SERVER_PASSWORD": "mdp-moteur",
        "QAF_MODELE": "simulation/demo", "QAF_FAUX_MODELE_URL": f"http://127.0.0.1:{p_modele}/v1",
        "OPENCODE_CONFIG_CONTENT": json.dumps(serveur),
        "SQUASH_MCP_DIR": str(MCP), "SQUASH_MCP_INDEX": str(MCP / "dist" / "index.js"),
        "SQUASH_TM_BASE_URL": squash.url, "SQUASH_TM_USERNAME": "qa", "SQUASH_TM_PASSWORD": "secret",
        "QAF_ADMIN_IDENTIFIANT": "admin", "QAF_ADMIN_MOT_DE_PASSE": "Provisoire123", "QAF_INTERVALLE_SUIVI_S": "0.5",
    }
    os.environ.pop("SQUASH_TM_API_TOKEN", None)
    os.environ.update(variables)
    oc = subprocess.Popen(["opencode", "serve", "--port", str(p_oc)], cwd=racine, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    attendre(lambda: _ok(httpx, f"http://127.0.0.1:{p_oc}/session/status"), 60)
    sys.path.insert(0, str(ICI.parent))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield {"client": client, "racine": racine, "squash": squash}
    oc.terminate()
    modele.terminate()
    squash.arreter()


def _ok(httpx, url):
    try:
        return httpx.get(url, auth=("opencode", "mdp-moteur"), timeout=2).status_code == 200
    except Exception:
        return False


def csrf(client, url="/"):
    h = client.get(url).text
    return re.search(r'name="csrf" value="([^"]+)"', h).group(1)


def connecter(client, ident, mdp):
    client.post("/deconnexion", data={"csrf": csrf(client, "/connexion")})
    r = client.post("/connexion", data={"identifiant": ident, "mot_de_passe": mdp, "csrf": csrf(client, "/connexion")})
    assert r.status_code in (200, 303)


def tache_finie(base, tid, client=None, accepter=True):
    def fin():
        t = base.tache(tid)
        if t["statut"] == "attente_confirmation" and client:
            for a in t["attente"] or []:
                if a["genre"] == "permission":
                    client.post(f"/taches/{tid}/permission", data={"demande": a["id"], "decision": "accepter" if accepter else "refuser",
                                                                   "csrf": csrf(client, f"/taches/{tid}")})
        return t if t["statut"] in ("termine", "echec", "annule") else None
    return attendre(fin, 180)


def test_parcours_temps_a(env):
    c, racine = env["client"], env["racine"]
    from app.main import base

    # Connexion de l'administrateur initial : changement de mot de passe obligatoire
    connecter(c, "admin", "Provisoire123")
    assert "/compte" in c.get("/").url.path
    c.post("/compte", data={"actuel": "Provisoire123", "nouveau": "Admin-2026-ok", "confirmation": "Admin-2026-ok", "csrf": csrf(c, "/compte")})
    assert c.get("/").url.path == "/"

    # Comptes
    for ident, nom, role in (("resp", "Awa Responsable", "responsable"), ("test", "Koffi Testeur", "testeur")):
        c.post("/admin/utilisateurs", data={"identifiant": ident, "nom": nom, "role": role, "mot_de_passe": "Provisoire456",
                                            "csrf": csrf(c, "/admin/utilisateurs")})
    for ident in ("resp", "test"):
        connecter(c, ident, "Provisoire456")
        c.post("/compte", data={"actuel": "Provisoire456", "nouveau": "Perso-2026-xx", "confirmation": "Perso-2026-xx", "csrf": csrf(c, "/compte")})

    # Le testeur ne crée pas de projet ; le responsable si (sans URL : site pas encore livré)
    connecter(c, "test", "Perso-2026-xx")
    assert c.get("/projets/nouveau").status_code == 403
    connecter(c, "resp", "Perso-2026-xx")
    r = c.post("/projets/nouveau", data={"code": "demo", "nom": "Démo", "url": "", "squash_id": "28", "csrf": csrf(c, "/projets/nouveau")})
    assert r.url.path == "/projets/demo"
    fiche = json.loads((racine / "projets/demo/projet.json").read_text(encoding="utf-8"))
    assert fiche["responsable"] == "Awa Responsable" and fiche["application"]["url"] == ""

    # Dépôt du cahier des charges (et refus d'un format interdit)
    cdc = (racine / "projets/saucedemo/01-entrant/cahier-des-charges.md").read_bytes()
    c.post("/projets/demo/documents", files=[("fichiers", ("cdc.md", cdc, "text/markdown"))], data={"csrf": csrf(c, "/projets/demo")})
    c.post("/projets/demo/documents", files=[("fichiers", ("virus.exe", b"x", "application/octet-stream"))], data={"csrf": csrf(c, "/projets/demo")})
    assert sorted(p.name for p in (racine / "projets/demo/01-entrant").iterdir()) == ["LISEZMOI.md", "cdc.md"]

    # Analyse par le testeur : vrai OpenCode, confirmation demandée puis accordée dans la page
    connecter(c, "test", "Perso-2026-xx")
    r = c.post("/projets/demo/analyser", data={"csrf": csrf(c, "/projets/demo")})
    tid = int(r.url.path.rsplit("/", 1)[1])
    vu_attente = attendre(lambda: base.tache(tid)["statut"] == "attente_confirmation" or base.tache(tid)["statut"] in ("termine", "echec"), 120)
    t = base.tache(tid)
    assert t["statut"] == "attente_confirmation", t["journal"]
    assert "cp -r projets/saucedemo" in t["attente"][0]["detail"]
    assert "Autoriser une fois" in c.get(f"/taches/{tid}").text
    t = tache_finie(base, tid, c)
    assert t["statut"] == "termine", t["journal"]
    assert t["resultat"]["controle"]["ok"]
    assert "Analyse terminée" in t["resultat"]["compte_rendu"]
    assert any(e["outil"] == "bash" for e in t["resultat"]["etapes"])
    assert (racine / "projets/demo/02-a-valider/cas-de-tests.xlsx").exists()

    # Relecture en ligne et documents
    assert "CT0001" in c.get("/projets/demo/cas/a-valider").text
    assert "Q-002" in c.get("/projets/demo/lire/02-a-valider/ambiguites.md").text

    # Correction par l'Excel renvoyé
    from openpyxl import load_workbook
    xlsx = c.get("/projets/demo/telecharger/02-a-valider/cas-de-tests.xlsx").content
    wb = load_workbook(io.BytesIO(xlsx))
    ws = wb["Cas de tests"]
    for ligne in ws.iter_rows(min_row=2):
        if ligne[0].value == "CT0003":
            ligne[2].value = "Bloquer la connexion quand le mot de passe est vide"
    sortie = io.BytesIO()
    wb.save(sortie)
    r = c.post("/projets/demo/vue", files={"fichier": ("cas-de-tests.xlsx", sortie.getvalue(), "application/octet-stream")},
               data={"csrf": csrf(c, "/projets/demo")})
    data = json.loads((racine / "projets/demo/02-a-valider/cas-de-tests.json").read_text(encoding="utf-8"))
    assert next(x for x in data["cas_de_tests"] if x["id"] == "CT0003")["titre"] == "Bloquer la connexion quand le mot de passe est vide"
    assert "pris en compte" in r.text

    # Un autre nom de fichier est refusé
    r = c.post("/projets/demo/vue", files={"fichier": ("autre.xlsx", sortie.getvalue(), "application/octet-stream")},
               data={"csrf": csrf(c, "/projets/demo")})
    assert "Seuls cas-de-tests.xlsx" in r.text

    # Validation : refusée au testeur, faite par le responsable
    assert c.post("/projets/demo/valider", data={"csrf": csrf(c, "/projets/demo")}).status_code == 403
    connecter(c, "resp", "Perso-2026-xx")
    c.post("/projets/demo/valider", data={"csrf": csrf(c, "/projets/demo")})
    assert (racine / "projets/demo/03-valide/cas-de-tests.json").exists()
    assert not (racine / "projets/demo/02-a-valider/cas-de-tests.json").exists()
    assert "validé par Awa Responsable" in (racine / "projets/demo/journal.md").read_text(encoding="utf-8")

    # Publication Squash : simulation, puis publication, puis plus rien à créer
    r = c.post("/projets/demo/publier/simulation", data={"csrf": csrf(c, "/projets/demo")})
    sim = tache_finie(base, int(r.url.path.rsplit("/", 1)[1]))
    assert sim["statut"] == "termine", sim["journal"]
    assert sim["resultat"]["resume"]["creer"] == 53
    assert len(env["squash"].store["testCases"]) == 0
    page = c.get("/projets/demo").text
    assert "Publier dans Squash" in page
    r = c.post("/projets/demo/publier", data={"simulation": sim["id"], "csrf": csrf(c, "/projets/demo")})
    pub = tache_finie(base, int(r.url.path.rsplit("/", 1)[1]))
    assert pub["statut"] == "termine", pub["journal"]
    assert len(env["squash"].store["testCases"]) == 27 and len(env["squash"].store["requirements"]) == 17
    r = c.post("/projets/demo/publier/simulation", data={"csrf": csrf(c, "/projets/demo")})
    sim2 = tache_finie(base, int(r.url.path.rsplit("/", 1)[1]))
    assert sim2["resultat"]["resume"] == {"creer": 0, "existe": 53, "recreer": 0}
    # Une ancienne simulation ne peut pas servir après une remise en relecture puis une nouvelle validation modifiée
    assert "Tout est déjà publié" in c.get("/projets/demo").text

    # Specs
    r = c.post("/projets/demo/specs", data={"csrf": csrf(c, "/projets/demo")})
    sp = tache_finie(base, int(r.url.path.rsplit("/", 1)[1]))
    assert sp["statut"] == "termine", sp["journal"]
    assert (racine / "projets/demo/04-livrables/specs/authentification.md").exists()


def test_securite(env):
    c = env["client"]
    c.post("/deconnexion", data={"csrf": csrf(c, "/connexion")})
    assert c.get("/projets/demo").url.path == "/connexion"
    assert c.get("/projets/demo/telecharger/02-a-valider/cas-de-tests.json").url.path == "/connexion"
    connecter(c, "test", "Perso-2026-xx")
    assert c.get("/projets/demo/telecharger/../../saas/donnees/.secret").status_code == 404
    assert c.get("/projets/demo/telecharger/projet.json").status_code == 404
    assert c.get("/projets/demo/telecharger/03-valide/.synchro.json").status_code == 404
    assert c.post("/projets/demo/specs", data={"csrf": "faux"}).status_code == 400
    assert c.get("/admin/utilisateurs").status_code == 403
    assert c.get("/projets/..%2Fsaucedemo").status_code == 404
    r = c.post("/connexion", data={"identifiant": "test", "mot_de_passe": "mauvais", "csrf": csrf(c, "/connexion")})
    assert "incorrect" in r.text
