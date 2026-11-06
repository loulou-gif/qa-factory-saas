# -*- coding: utf-8 -*-
"""Temps B, lot 1 : application testée, comptes de test chiffrés, tâche « tester », résultats,
rapport, modifications de cas proposées et validées.

Le moteur IA est remplacé par un faux agent (il écrit les résultats de référence de SauceDemo) :
cd saas && python -m pytest -q tests/test_tests_application.py
"""
import html
import json
import shutil
import time

import pytest

from conftest import connecter, csrf, jx
from test_parametres import MDP, creer


def poster(c, url, donnees, page):
    return c.post(url, data={**donnees, "csrf": csrf(c, page)})


def projet_valide(racine, code):
    d = racine / "projets" / code
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(racine / "projets" / "saucedemo", d)
    for f in (d / "02-a-valider").iterdir():
        if f.name != "LISEZMOI.md":
            shutil.move(str(f), str(d / "03-valide" / f.name))
    fiche = json.loads((d / "projet.json").read_text(encoding="utf-8"))
    fiche["application"] = {}
    (d / "projet.json").write_text(json.dumps(fiche, ensure_ascii=False), encoding="utf-8")
    return d


def test_application_et_comptes(espace, monkeypatch):
    from app import campagnes
    from app.config import reglages
    from app.main import base
    c, racine = espace["client"], espace["racine"]
    code = "appli-reglages"
    projet_valide(racine, code)
    creer("nora")
    connecter(c, "nora", MDP)
    page = f"/projets/{code}/application"

    # Lien normalisé ; réseau interne refusé sur le service public
    poster(c, page, {"url": "recette.exemple.com/app", "actions": "donnees-de-test", "domaines": "sso.exemple.com"}, page)
    a = campagnes.application(code)
    assert a == {"url": "https://recette.exemple.com/app", "actions": "donnees-de-test", "autres_domaines": ["https://sso.exemple.com"]} or \
        "réseau" in html.unescape(c.get(page).text)
    monkeypatch.setattr(reglages, "squash_reseau_prive", False)
    r = html.unescape(poster(c, page, {"url": "http://127.0.0.1:9/", "actions": "lecture-seule", "domaines": ""}, page).text)
    assert "réseau interne" in r and "de l'application" in r
    monkeypatch.setattr(reglages, "squash_reseau_prive", True)

    # Comptes : chiffrés, mot de passe jamais réaffiché, secrets nommés pour le navigateur
    poster(c, page + "/comptes", {"libelle": "Client", "identifiant": "standard_user", "mot_de_passe": "secret_sauce"}, page)
    poster(c, page + "/comptes", {"libelle": "Bloqué", "identifiant": "locked_out_user", "mot_de_passe": "secret_sauce"}, page)
    brut = base.tous("SELECT identifiant, secret FROM comptes_test WHERE projet = ?", (code,))
    assert len(brut) == 2 and all("standard_user" not in x["identifiant"] and "secret_sauce" not in x["secret"] for x in brut)
    texte = c.get(page).text
    assert "standard_user" in texte and "secret_sauce" not in texte
    libelles, valeurs = campagnes.secrets(base, code)
    assert libelles == ["Client", "Bloqué"]
    assert valeurs == {"COMPTE_1_IDENTIFIANT": "standard_user", "COMPTE_1_MOT_DE_PASSE": "secret_sauce",
                       "COMPTE_2_IDENTIFIANT": "locked_out_user", "COMPTE_2_MOT_DE_PASSE": "secret_sauce"}
    cid = base.un("SELECT id FROM comptes_test WHERE projet = ? AND libelle = 'Bloqué'", (code,))["id"]
    poster(c, f"{page}/comptes/{cid}/supprimer", {}, page)
    assert [x["libelle"] for x in campagnes.comptes(base, code)] == ["Client"]
    details = " ".join(a["detail"] or "" for a in base.tous("SELECT detail FROM audit WHERE projet = ?", (code,)))
    assert "secret_sauce" not in details


def test_campagne_de_tests_complete(espace, monkeypatch):
    from app import campagnes, moteur as module_moteur
    from app.config import reglages
    from app.main import base
    c, racine = espace["client"], espace["racine"]
    code = "appli-tests"
    d = projet_valide(racine, code)
    creer("omar")
    connecter(c, "omar", MDP)
    page = f"/projets/{code}/application"

    # Sans lien : le projet invite à renseigner l'application, le lancement est refusé
    assert "Renseigner l'application" in html.unescape(c.get(f"/projets/{code}").text)
    assert jx(c, f"/projets/{code}/tester", {}, f"/projets/{code}").status_code == 409
    poster(c, page, {"url": "https://www.saucedemo.com", "actions": "lecture-seule", "domaines": ""}, page)
    poster(c, page + "/comptes", {"libelle": "Client", "identifiant": "standard_user", "mot_de_passe": "secret_sauce"}, page)

    vu = {}
    m = module_moteur.moteur

    def ajouter_navigateur(nom, config):
        vu["navigateur"] = (nom, config)

    def executer(base_, tid, commande, arguments, outils=None, modele=None, secours=None):
        vu["commande"] = (commande, arguments, outils)
        camp = json.loads((d / "04-livrables" / "execution" / arguments.split()[-1] / "campagne.json").read_text(encoding="utf-8"))
        vu["campagne"] = camp
        ref = racine / "projets" / "saucedemo" / "04-livrables" / "execution-reference"
        dst = d / "04-livrables" / "execution" / camp["id"]
        shutil.copytree(ref / "resultats", dst / "resultats", dirs_exist_ok=True)
        shutil.copytree(ref / "captures", dst / "captures", dirs_exist_ok=True)
        return {"compte_rendu": "Fini.", "cout_usd": 0.42}

    monkeypatch.setattr(m, "disponible", lambda: (True, ""))
    monkeypatch.setattr(m, "ajouter_navigateur", ajouter_navigateur)
    monkeypatch.setattr(m, "retirer_navigateur", lambda nom: vu.setdefault("retire", nom))
    monkeypatch.setattr(m, "executer", executer)
    monkeypatch.setattr(reglages, "modele", "openrouter/fournisseur/modele")

    r = jx(c, f"/projets/{code}/tester", {}, f"/projets/{code}")
    assert r.status_code == 200, r.text
    tid = r.json()["tache"]
    assert "Arrêter les tests" in c.get(f"/projets/{code}").text
    for _ in range(120):
        p = c.get(f"/taches/{tid}/progression").json()
        if not p["actif"]:
            break
        time.sleep(0.25)
    assert p["statut"] == "termine", p

    # Navigateur de la tâche : secrets, domaines, dossier de la campagne ; seuls ses outils sont actifs
    nom, config = vu["navigateur"]
    assert nom == f"nav{tid}" and vu["retire"] == nom
    env = config["environment"]
    assert json.loads(env["QAF_NAV_SECRETS"]) == {"COMPTE_1_IDENTIFIANT": "standard_user", "COMPTE_1_MOT_DE_PASSE": "secret_sauce"}
    assert env["QAF_NAV_ORIGINES"] == "https://www.saucedemo.com" and config["cwd"].endswith(vu["campagne"]["id"])
    commande, arguments, outils = vu["commande"]
    assert commande == "tester" and arguments == f"{code} campagne {vu['campagne']['id']}"
    assert outils == {"nav*": False, f"nav{tid}_*": True}
    # La fiche de campagne lue par l'agent ne contient que les NOMS des secrets
    camp_texte = json.dumps(vu["campagne"])
    assert "secret_sauce" not in camp_texte and "standard_user" not in camp_texte and "COMPTE_1_MOT_DE_PASSE" in camp_texte

    # Résultats : courts, avec anomalie, couverture et téléchargements
    t = html.unescape(c.get(f"/projets/{code}/tests").text)
    assert "27/27" in t and "96 %" in t and "Commande possible avec un panier vide" in t
    assert "2 cas à corriger" in t and "EX-015" in t
    chemin = f"04-livrables/execution/{vu['campagne']['id']}"
    for f in ("rapport.html", "rapport.xlsx", "captures/CT0027_02_commande-panier-vide.png"):
        assert c.get(f"/projets/{code}/telecharger/{chemin}/{f}").status_code == 200, f
    assert "2 cas à corriger" in html.unescape(c.get(f"/projets/{code}").text)

    # Modifications proposées : avant/après, puis une acceptée, une refusée
    t = html.unescape(c.get(f"/projets/{code}/tests/modifications").text)
    assert "CT0002" in t and "CT0021" in t and "Epic sadface: Username is required" in t
    version = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))["meta"]["version"]
    r = jx(c, f"/projets/{code}/tests/modifications", {"campagne": vu["campagne"]["id"], "acceptes": ["CT0002"]}, f"/projets/{code}")
    assert r.status_code == 200, r.text
    data = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
    ct2 = next(x for x in data["cas_de_tests"] if x["id"] == "CT0002")
    ct21 = next(x for x in data["cas_de_tests"] if x["id"] == "CT0021")
    assert data["meta"]["version"] == version + 1 and "Username is required" in ct2["etapes"][-1]["resultat_attendu"]
    assert "Thank you" not in ct21["etapes"][-1]["resultat_attendu"]
    assert jx(c, f"/projets/{code}/tests/modifications", {"campagne": vu["campagne"]["id"], "acceptes": []},
              f"/projets/{code}").status_code == 400  # déjà traitées
    assert "cas à corriger" not in html.unescape(c.get(f"/projets/{code}").text)
    assert "Acceptée" in c.get(f"/projets/{code}/tests/modifications").text
