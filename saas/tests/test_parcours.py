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
    m = re.search(r'name="csrf" content="([^"]+)"', h) or re.search(r'name="csrf" value="([^"]+)"', h)
    return m.group(1)


def connecter(client, ident, mdp):
    client.post("/deconnexion", data={"csrf": csrf(client, "/connexion")})
    r = client.post("/connexion", data={"identifiant": ident, "mot_de_passe": mdp, "csrf": csrf(client, "/connexion")})
    assert r.status_code in (200, 303)


def jx(client, url, corps=None, page="/"):
    return client.post(url, json=corps or {}, headers={"X-CSRF": csrf(client, page), "Accept": "application/json"})


def suivre(client, tid, accepter=True, delai=180):
    def fin():
        d = client.get(f"/taches/{tid}/progression").json()
        for a in d["attente"]:
            if a["genre"] == "permission":
                jx(client, f"/taches/{tid}/permission", {"demande": a["id"], "accepter": accepter})
        return d if not d["actif"] else None
    return attendre(fin, delai)


def test_parcours_temps_a(env):
    c, racine = env["client"], env["racine"]

    # Administrateur initial : changement de mot de passe obligatoire, puis création d'un testeur
    connecter(c, "admin", "Provisoire123")
    assert "/compte" in c.get("/").url.path
    c.post("/compte", data={"actuel": "Provisoire123", "nouveau": "Admin-2026-ok", "confirmation": "Admin-2026-ok", "csrf": csrf(c, "/compte")})
    c.post("/admin/utilisateurs", data={"identifiant": "test", "nom": "Koffi Testeur", "role": "testeur", "mot_de_passe": "Provisoire456",
                                        "csrf": csrf(c, "/admin/utilisateurs")})
    connecter(c, "test", "Provisoire456")
    c.post("/compte", data={"actuel": "Provisoire456", "nouveau": "Perso-2026-xx", "confirmation": "Perso-2026-xx", "csrf": csrf(c, "/compte")})
    accueil = c.get("/").text
    assert 'id="depot"' in accueil and "Déposez ici votre cahier des charges" in accueil

    # Un format interdit est refusé
    r = c.post("/demarrer", files=[("fichiers", ("virus.exe", b"x", "application/octet-stream"))], headers={"X-CSRF": csrf(c)})
    assert r.status_code == 400 and "format non accepté" in r.json()["erreur"]

    # Déposer, c'est lancer : projet créé depuis le nom du fichier, analyse par le vrai OpenCode
    cdc = (racine / "projets/saucedemo/01-entrant/cahier-des-charges.md").read_bytes()
    # Contenu insuffisant : refusé avant tout appel à l'IA, sans créer de projet
    r = c.post("/demarrer", files=[("fichiers", ("note.md", b"# Projet\nA faire plus tard.", "text/markdown"))],
               headers={"X-CSRF": csrf(c), "Accept": "application/json"})
    assert r.status_code == 422 and "Pas assez de contenu exploitable" in r.json()["erreur"] and "mots seulement" in r.json()["erreur"]
    r = c.post("/demarrer", files=[("fichiers", ("ecran.png", b"\x89PNG", "image/png"))],
               headers={"X-CSRF": csrf(c), "Accept": "application/json"})
    assert r.status_code == 422 and "maquettes seules" in r.json()["erreur"]
    assert not (racine / "projets/note").exists() and not (racine / "projets/ecran").exists()

    # Plusieurs documents d'un coup : le cahier des charges et une maquette
    r = c.post("/demarrer", files=[("fichiers", ("Cahier_des_charges_Boutique.md", cdc, "text/markdown")),
                                   ("fichiers", ("maquette.png", b"\x89PNG", "image/png"))],
               headers={"X-CSRF": csrf(c), "Accept": "application/json"})
    assert r.status_code == 200, r.text
    d = r.json()
    code, tid = d["projet"], d["tache"]
    assert code == "cahier-des-charges-boutique" and d["nom"] == "Cahier des charges Boutique"
    assert (racine / f"projets/{code}/01-entrant/maquette.png").exists()
    assert (racine / f"projets/{code}/01-entrant/_texte/Cahier_des_charges_Boutique.md.txt").exists()
    # Aucune demande d'accord n'est présentée au testeur : les commandes utiles sont autorisées d'avance
    vu = attendre(lambda: (lambda x: x if x["attente"] or not x["actif"] else None)(c.get(f"/taches/{tid}/progression").json()), 120)
    assert not vu["attente"], vu
    fin = suivre(c, tid)
    assert fin["statut"] == "termine" and fin["pourcentage"] == 100 and fin["message"] == "Génération terminée", fin

    # Fichiers produits, vues digestes
    page = c.get(f"/projets/{code}").text
    assert "27 cas sur 4 fonctionnalités" in page and "dont 2 bloquantes" in page and "Relire les cas de tests" in page
    assert "Q-005" in c.get(f"/projets/{code}/questions").text
    assert "JDD-001" in c.get(f"/projets/{code}/donnees").text
    cas = c.get(f"/projets/{code}/cas").text
    assert "CT0001" in cas and "Je dois voir" in cas and "16 nominaux" in cas and 'id="enregistrer"' in cas

    # Contrôles des modifications
    r = jx(c, f"/projets/{code}/enregistrer", {"modifications": [{"id": "CT0003", "etapes": []}]}, f"/projets/{code}/cas")
    assert r.status_code == 400 and "au moins une étape" in r.json()["erreur"]
    assert not (racine / f"projets/{code}/03-valide/cas-de-tests.json").exists()

    # Enregistrer = modifications reportées + validation immédiate + specs
    modif = {"id": "CT0003", "titre": "Bloquer la connexion quand le mot de passe est vide",
             "etapes": [{"action": "Saisir le nom d'utilisateur seul", "resultat_attendu": "Le champ est rempli."},
                        {"action": "Cliquer sur le bouton de connexion", "resultat_attendu": "Un message indique que le mot de passe est obligatoire."}]}
    r = jx(c, f"/projets/{code}/enregistrer", {"modifications": [modif]}, f"/projets/{code}/cas")
    assert r.status_code == 200 and r.json()["redirection"] == f"/projets/{code}", r.text
    valide = json.loads((racine / f"projets/{code}/03-valide/cas-de-tests.json").read_text(encoding="utf-8"))
    ct3 = next(x for x in valide["cas_de_tests"] if x["id"] == "CT0003")
    assert ct3["titre"] == modif["titre"] and len(ct3["etapes"]) == 2 and valide["meta"]["version"] == 3
    assert not (racine / f"projets/{code}/02-a-valider/cas-de-tests.json").exists()
    assert (racine / f"projets/{code}/04-livrables/specs/authentification.md").exists()
    assert "validé par Koffi Testeur" in (racine / f"projets/{code}/journal.md").read_text(encoding="utf-8")
    page = c.get(f"/projets/{code}").text
    assert "Enregistré et validé" in page and "Envoyer dans Squash" in page
    assert "lecture seule" in c.get(f"/projets/{code}/cas").text

    # Squash : vérification puis envoi, sans doublon à la relance
    r = jx(c, f"/projets/{code}/squash/simuler", {"squash_id": "abc"}, f"/projets/{code}")
    assert r.status_code == 400
    r = jx(c, f"/projets/{code}/squash/simuler", {"squash_id": "28"}, f"/projets/{code}")
    sim = suivre(c, r.json()["tache"])
    assert sim["statut"] == "termine", sim
    assert sim["simulation"]["resume"]["creer"] == 53 and sim["simulation"]["projet"]["id"] == 28
    assert len(env["squash"].store["testCases"]) == 0
    r = jx(c, f"/projets/{code}/squash/publier", {"simulation": r.json()["tache"]}, f"/projets/{code}")
    pub = suivre(c, r.json()["tache"])
    assert pub["statut"] == "termine" and pub["crees"] == 53 and pub["message"] == "Envoyé dans Squash", pub
    assert len(env["squash"].store["testCases"]) == 27 and len(env["squash"].store["requirements"]) == 17
    assert "27 cas et 17 exigences sont dans Squash" in c.get(f"/projets/{code}").text
    r = jx(c, f"/projets/{code}/squash/simuler", {}, f"/projets/{code}")
    sim2 = suivre(c, r.json()["tache"])
    assert sim2["simulation"]["resume"] == {"creer": 0, "existe": 53, "recreer": 0}

    # Modifier à nouveau : les cas redeviennent modifiables
    c.post(f"/projets/{code}/rouvrir", data={"csrf": csrf(c, f"/projets/{code}")})
    assert (racine / f"projets/{code}/02-a-valider/cas-de-tests.json").exists()
    assert 'id="enregistrer"' in c.get(f"/projets/{code}/cas").text
    assert "Reprendre" in c.get("/").text and "Cahier des charges Boutique" in c.get("/projets").text


def test_securite(env):
    c = env["client"]
    code = "cahier-des-charges-boutique"
    c.post("/deconnexion", data={"csrf": csrf(c, "/connexion")})
    assert c.get(f"/projets/{code}").url.path == "/connexion"
    assert c.get(f"/projets/{code}/telecharger/02-a-valider/cas-de-tests.json").url.path == "/connexion"
    assert c.post("/demarrer", files=[("fichiers", ("a.md", b"x", "text/markdown"))], headers={"X-CSRF": "x"}).status_code in (400, 401)
    connecter(c, "test", "Perso-2026-xx")
    assert c.get(f"/projets/{code}/telecharger/../../saas/donnees/.secret").status_code == 404
    assert c.get(f"/projets/{code}/telecharger/projet.json").status_code == 404
    assert c.get(f"/projets/{code}/telecharger/02-a-valider/.synchro.json").status_code == 404
    assert c.post(f"/projets/{code}/enregistrer", json={}, headers={"X-CSRF": "faux"}).status_code == 400
    assert c.get("/admin/utilisateurs").status_code == 403
    assert c.get("/projets/..%2Fsaucedemo").status_code == 404
    r = c.post("/connexion", data={"identifiant": "test", "mot_de_passe": "mauvais", "csrf": csrf(c, "/connexion")})
    assert "incorrect" in r.text
