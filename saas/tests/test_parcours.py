# -*- coding: utf-8 -*-
"""Parcours complet du temps A dans l'application web, avec le vrai OpenCode (faux modèle) et un faux Squash.

Lancement : cd saas && python -m pytest -q tests
Prérequis : opencode, node, python avec fastapi/httpx/openpyxl/python-docx/cryptography, et le MCP squash-tm
compilé (SQUASH_MCP_DIR, défaut ../squash-tm-mcp à côté du dépôt). Espace commun : conftest.py.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import connecter, csrf, jx, regler_squash

ICI = Path(__file__).resolve().parent


def attendre(cond, delai=120, pas=0.5):
    fin = time.time() + delai
    while time.time() < fin:
        r = cond()
        if r:
            return r
        time.sleep(pas)
    raise AssertionError("délai dépassé")


@pytest.fixture(scope="module")
def env(espace):
    """Démarre le faux modèle et OpenCode sur les ports réservés par l'espace commun."""
    ports = espace["ports"]
    modele = subprocess.Popen([sys.executable, str(ICI.parent / "dev" / "faux_modele.py"), str(ports["modele"])])
    oc = subprocess.Popen(["opencode", "serve", "--port", str(ports["moteur"])], cwd=espace["racine"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx
        attendre(lambda: _ok(httpx, f"http://127.0.0.1:{ports['moteur']}/session/status"), 60)
        yield espace
    finally:
        oc.terminate()
        modele.terminate()


def _ok(httpx, url):
    try:
        return httpx.get(url, auth=("opencode", "mdp-moteur"), timeout=2).status_code == 200
    except Exception:
        return False


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
    # Le testeur connecte son propre Squash depuis l'application
    assert "Squash est connecté : 2 projets visibles" in regler_squash(c, env["squash"].url).text
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

    # Jeux de données modifiés dans l'application
    r = jx(c, f"/projets/{code}/donnees", {"modifications": [{"id": "JDD-004", "lignes": [
        {"champ": "Prénom", "valeur": "Aya", "remarque": ""}, {"champ": "Nom", "valeur": "Kouassi", "remarque": ""},
        {"champ": "Code postal", "valeur": "00225", "remarque": "format à confirmer (Q-008)"},
        {"champ": "Ville", "valeur": "Abidjan", "remarque": "ajouté"}]}]}, f"/projets/{code}/donnees")
    assert r.status_code == 200, r.text
    md = (racine / f"projets/{code}/03-valide/jeux-de-donnees.md").read_text(encoding="utf-8")
    assert "| Prénom | `Aya` |" in md and "| Ville | `Abidjan` | ajouté |" in md and "JDD-005" in md
    r = jx(c, f"/projets/{code}/donnees", {"modifications": [{"id": "JDD-004", "lignes": [
        {"champ": "Nom", "valeur": "a"}, {"champ": "nom", "valeur": "b"}]}]}, f"/projets/{code}/donnees")
    assert r.status_code == 400 and "même nom" in r.json()["erreur"]

    # Squash : projets proposés par leur nom
    projets_squash = c.get(f"/projets/{code}/squash/projets", headers={"Accept": "application/json"}).json()["projets"]
    assert {"id": 28, "nom": "SauceDemo"} in projets_squash and len(projets_squash) == 2
    page = c.get(f"/projets/{code}").text
    assert "2 cas attendent la réponse à une question bloquante" in page

    # Squash : vérification puis envoi ; les cas suspendus à une question bloquante restent en attente
    r = jx(c, f"/projets/{code}/squash/simuler", {"squash_id": "abc"}, f"/projets/{code}")
    assert r.status_code == 400
    r = jx(c, f"/projets/{code}/squash/simuler", {"squash_id": "28", "squash_nom": "SauceDemo", "url": "pas-un-lien"}, f"/projets/{code}")
    assert r.status_code == 400 and "http" in r.json()["erreur"]
    r = jx(c, f"/projets/{code}/squash/simuler", {"squash_id": "28", "squash_nom": "SauceDemo", "url": "https://recette.boutique.test"},
           f"/projets/{code}")
    sim = suivre(c, r.json()["tache"])
    assert sim["statut"] == "termine", sim
    assert sim["simulation"]["exclus"] == 2 and sim["simulation"]["projet"]["id"] == 28
    a_creer = sim["simulation"]["resume"]["creer"]
    fiche = json.loads((racine / f"projets/{code}/projet.json").read_text(encoding="utf-8"))
    assert fiche["application"]["url"] == "https://recette.boutique.test" and fiche["squash"]["projet_nom"] == "SauceDemo"
    assert len(env["squash"].store["testCases"]) == 0
    r = jx(c, f"/projets/{code}/squash/publier", {"simulation": r.json()["tache"]}, f"/projets/{code}")
    pub = suivre(c, r.json()["tache"])
    assert pub["statut"] == "termine" and pub["crees"] == a_creer and pub["message"] == "Envoyé dans Squash", pub
    store = env["squash"].store
    assert len(store["testCases"]) == 25 and len(store["requirements"]) == 17
    refs = {tc["reference"] for tc in store["testCases"].values()}
    assert "CT0007" not in refs and "CT0027" not in refs

    # Jeux de données dans Squash : paramètres et valeurs, cités dans le prérequis
    ct21 = next(tc for tc in store["testCases"].values() if tc["reference"] == "CT0021")
    assert "${Prenom}" in ct21["prerequisite"] and "${Code_postal}" in ct21["prerequisite"]
    noms_params = {x["name"] for x in ct21["parameters"]}
    assert {"Prenom", "Nom", "Code_postal", "Ville"} <= noms_params
    jdd4 = next(d for d in store["datasets"].values() if d["test_case"] == ct21["id"] and d["name"].startswith("JDD-004"))
    valeurs = {v["parameter_name"]: v["parameter_value"] for v in jdd4["parameter_values"]}
    assert valeurs["Prenom"] == "Aya" and valeurs["Ville"] == "Abidjan"
    assert "25 cas et 17 exigences sont dans Squash" in c.get(f"/projets/{code}").text

    # Répondre aux questions bloquantes (une réponse, un faux positif) : les deux cas partent à leur tour
    r = jx(c, f"/projets/{code}/questions/Q-002", {"reponse": ""}, f"/projets/{code}/questions")
    assert r.status_code == 400
    r = jx(c, f"/projets/{code}/questions/Q-002", {"reponse": "Compte locked_out_user fourni par le client"}, f"/projets/{code}/questions")
    assert r.status_code == 200 and r.json()["statut"] == "répondue" and r.json()["bloques"] == 1
    r = jx(c, f"/projets/{code}/questions/Q-005", {"faux_positif": True}, f"/projets/{code}/questions")
    assert r.json()["statut"] == "close" and r.json()["bloques"] == 0
    amb = (racine / f"projets/{code}/03-valide/ambiguites.md").read_text(encoding="utf-8")
    assert "Compte locked_out_user fourni par le client (Koffi Testeur" in amb and "Sans objet : faux positif" in amb
    assert projets_controle_ok(racine, code)
    page = c.get(f"/projets/{code}").text
    assert "Envoyer 2 nouveaux cas dans Squash" in page and "attendent la réponse" not in page
    r = jx(c, f"/projets/{code}/squash/simuler", {}, f"/projets/{code}")
    sim2 = suivre(c, r.json()["tache"])
    assert sim2["simulation"]["resume"]["creer"] == 2 and sim2["simulation"]["exclus"] == 0, sim2
    r = jx(c, f"/projets/{code}/squash/publier", {"simulation": r.json()["tache"]}, f"/projets/{code}")
    assert suivre(c, r.json()["tache"])["crees"] == 2
    assert len(store["testCases"]) == 27
    r = jx(c, f"/projets/{code}/squash/simuler", {}, f"/projets/{code}")
    sim3 = suivre(c, r.json()["tache"])
    assert sim3["simulation"]["resume"]["creer"] == 0 and not sim3["simulation"]["jeux"].get("a_creer")

    # Un jeu déjà renseigné dans Squash n'est jamais modifié, même si on le change dans l'application
    jx(c, f"/projets/{code}/donnees", {"modifications": [{"id": "JDD-004", "lignes": [{"champ": "Prénom", "valeur": "Autre"}]}]},
       f"/projets/{code}/donnees")
    r = jx(c, f"/projets/{code}/squash/simuler", {}, f"/projets/{code}")
    sim4 = suivre(c, r.json()["tache"])
    assert sim4["simulation"]["jeux"]["a_completer"] == 0 and sim4["simulation"]["jeux"]["deja_renseignes"] > 0
    assert {v["parameter_name"]: v["parameter_value"] for v in jdd4["parameter_values"]}["Prenom"] == "Aya"

    # Modifier à nouveau : les cas redeviennent modifiables
    c.post(f"/projets/{code}/rouvrir", data={"csrf": csrf(c, f"/projets/{code}")})
    assert (racine / f"projets/{code}/02-a-valider/cas-de-tests.json").exists()
    assert 'id="enregistrer"' in c.get(f"/projets/{code}/cas").text
    assert "Reprendre" in c.get("/").text and "Cahier des charges Boutique" in c.get("/projets").text


def projets_controle_ok(racine, code):
    r = subprocess.run([sys.executable, str(racine / "outils" / "controle.py"), code, "--dossier", "03-valide"],
                       cwd=racine, capture_output=True, text=True)
    return r.returncode == 0


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
