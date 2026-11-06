# -*- coding: utf-8 -*-
"""Connexion de chaque utilisateur à son Squash : réglage dans l'application, test, chiffrement, isolation.

Ne lance pas le moteur IA : cd saas && python -m pytest -q tests/test_parametres.py
"""
import base64
import json
import html

import pytest

from conftest import connecter, jx, regler_squash
from faux_squash import JETON, JETON_SANS_JWT

MDP = "Motdepasse-2026"


def creer(ident):
    from app.db import maintenant
    from app.main import base
    from app.securite import hacher
    if not base.un("SELECT id FROM utilisateurs WHERE identifiant = ?", (ident,)):
        base.x("INSERT INTO utilisateurs (identifiant, nom, role, mot_de_passe, doit_changer, cree_le) VALUES (?,?,?,?,0,?)",
               (ident, ident.capitalize(), "testeur", hacher(MDP), maintenant()))
    return base.un("SELECT id FROM utilisateurs WHERE identifiant = ?", (ident,))["id"]


def connexion_de(uid):
    from app import connexions
    from app.main import base
    return connexions.lire(base, uid)


def adresse(squash):
    """Ce qu'un utilisateur colle : l'adresse de Squash, sans /api/rest/latest."""
    return squash.url.rsplit("/api/rest/latest", 1)[0]


def test_adresse_normalisee(espace):
    from app.connexions import ErreurConnexion, adresse_affichee, normaliser_adresse
    assert normaliser_adresse("squash.exemple.com/squash/") == "https://squash.exemple.com/squash/api/rest/latest"
    assert normaliser_adresse(" https://Squash.Exemple.com/squash/api/rest/v4 ") == "https://squash.exemple.com/squash/api/rest/latest"
    assert normaliser_adresse("http://h:8080") == "http://h:8080/api/rest/latest"
    assert adresse_affichee("https://s.ex/squash/api/rest/latest") == "https://s.ex/squash"
    for mauvaise in ("", "ftp://squash.exemple.com", "https://moi:mdp@squash.exemple.com/squash"):
        with pytest.raises(ErreurConnexion):
            normaliser_adresse(mauvaise)


def test_reseau_interne_refuse_par_defaut(espace, monkeypatch):
    from app.config import reglages
    monkeypatch.setattr(reglages, "squash_reseau_prive", False)
    c, squash = espace["client"], espace["squash"]
    uid = creer("ines")
    connecter(c, "ines", MDP)
    avant = len(squash.authentifications)
    r = regler_squash(c, adresse(squash))
    assert "réseau interne" in r.text and "Connexion non enregistrée" in r.text
    assert len(squash.authentifications) == avant  # Squash n'a même pas été contacté
    assert connexion_de(uid) is None


def test_connexion_par_utilisateur(espace):
    from app import connexions
    from app.main import base
    c, squash = espace["client"], espace["squash"]
    ana, bob = creer("ana"), creer("bob")
    connecter(c, "ana", MDP)

    # Sans connexion : la liste des projets et l'envoi demandent de connecter Squash
    r = c.get("/projets/saucedemo/squash/projets", headers={"Accept": "application/json"})
    assert r.status_code == 409 and "Connectez d'abord votre Squash" in r.json()["erreur"]
    assert jx(c, "/projets/saucedemo/squash/simuler", {"squash_id": "28"}, "/projets/saucedemo").status_code == 409
    assert 'href="/parametres/squash"' in c.get("/projets").text

    # Erreurs expliquées, rien d'enregistré
    assert "refuse ce compte" in html.unescape(regler_squash(c, adresse(squash), secret="mauvais").text)
    assert "Aucune API Squash" in html.unescape(regler_squash(c, adresse(squash) + "/ailleurs").text)
    assert "n'accepte pas les jetons" in html.unescape(regler_squash(c, adresse(squash), mode="jeton", secret=JETON_SANS_JWT).text)
    page = html.unescape(regler_squash(c, adresse(squash) + "/ici", identifiant="").text)
    assert "Indiquez l'identifiant" in page
    assert f'value="{adresse(squash)}/ici"' in page  # la saisie est reproposée après une erreur (jamais le secret)
    assert connexion_de(ana) is None

    # Connexion réussie : adresse normalisée, secret chiffré, jamais réaffiché
    r = regler_squash(c, adresse(squash) + "/")
    assert "Squash est connecté : 2 projets visibles avec ce compte." in r.text, r.text
    cx = connexion_de(ana)
    assert cx["url"] == squash.url and cx["mode"] == "compte" and cx["identifiant"] == "qa" and cx["projets_visibles"] == 2
    assert cx["secret"] != "secret" and connexions.dechiffrer(cx["secret"]) == "secret"
    page = html.unescape(c.get("/parametres/squash").text)
    assert "Connecté à " + adresse(squash) in page and "avec le compte qa" in page
    assert cx["secret"] not in page and 'value="secret"' not in page

    # Les appels à Squash utilisent ce compte
    r = c.get("/projets/saucedemo/squash/projets", headers={"Accept": "application/json"})
    assert r.status_code == 200 and {"id": 28, "nom": "SauceDemo"} in r.json()["projets"]
    assert squash.authentifications[-1] == "Basic " + base64.b64encode(b"qa:secret").decode()

    # Secret laissé vide : gardé si rien d'autre ne change ; jamais réutilisé pour une autre adresse
    assert "Squash est connecté" in html.unescape(regler_squash(c, adresse(squash), secret="").text)
    autre = adresse(squash).replace("127.0.0.1", "localhost")
    nb = len(squash.authentifications)
    assert "Saisissez le mot de passe" in html.unescape(regler_squash(c, autre, secret="").text)
    assert len(squash.authentifications) == nb and connexion_de(ana)["url"] == squash.url

    # Chaque utilisateur a sa propre connexion
    connecter(c, "bob", MDP)
    assert c.get("/projets/saucedemo/squash/projets", headers={"Accept": "application/json"}).status_code == 409
    assert "Connecté à" not in c.get("/parametres/squash").text
    assert "Squash est connecté" in html.unescape(regler_squash(c, adresse(squash), mode="jeton", identifiant="ignoré", secret=JETON).text)
    assert squash.authentifications[-1] == f"Bearer {JETON}"
    assert connexion_de(bob)["identifiant"] == "" and connexion_de(ana)["mode"] == "compte"

    # Suppression : le secret est effacé, l'envoi redemande une connexion
    from conftest import csrf
    c.post("/parametres/squash/supprimer", data={"csrf": csrf(c, "/parametres/squash")})
    assert connexion_de(bob) is None and connexion_de(ana) is not None
    assert c.get("/projets/saucedemo/squash/projets", headers={"Accept": "application/json"}).status_code == 409

    # Le journal d'audit trace les réglages sans jamais contenir de secret
    details = " ".join(a["detail"] or "" for a in base.tous("SELECT detail FROM audit WHERE action LIKE 'connexion-squash%'"))
    assert adresse(squash) in details and "secret" not in details and JETON not in details


def test_environnement_du_module_squash(espace, monkeypatch):
    """Le module Squash reçoit les identifiants de l'utilisateur, et aucun secret du serveur."""
    from app import connexions
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-ia")
    monkeypatch.setenv("SQUASH_TM_PASSWORD", "compte-de-service")
    cx = {"url": "https://s.ex/squash/api/rest/latest", "mode": "compte", "identifiant": "ana", "secret": connexions.chiffrer("mdp-ana")}
    env = connexions.environnement(cx)
    assert env["SQUASH_TM_USERNAME"] == "ana" and env["SQUASH_TM_PASSWORD"] == "mdp-ana"
    assert env["SQUASH_TM_BASE_URL"] == cx["url"] and "SQUASH_TM_API_TOKEN" not in env
    assert "OPENROUTER_API_KEY" not in env and "QAF_SECRET" not in env and "OPENCODE_SERVER_PASSWORD" not in env


def test_envoi_avec_la_connexion_de_l_utilisateur(espace):
    """Simulation et envoi dans Squash avec la connexion de la personne connectée ;
    un projet déjà envoyé sur une instance n'est jamais envoyé sur une autre."""
    import shutil
    import time

    from faux_squash import FauxSquash

    from app import connexions
    c, squash, racine = espace["client"], espace["squash"], espace["racine"]
    code = "boutique-envoi"
    d = racine / "projets" / code
    shutil.copytree(racine / "projets" / "saucedemo", d)
    for f in (d / "02-a-valider").iterdir():  # analyse de référence, marquée validée
        if f.name != "LISEZMOI.md":
            shutil.move(str(f), str(d / "03-valide" / f.name))
    uid = creer("chloe")
    connecter(c, "chloe", MDP)
    assert "Connecter Squash" in c.get(f"/projets/{code}").text
    regler_squash(c, adresse(squash))
    assert "Envoi vers " + adresse(squash) in html.unescape(c.get(f"/projets/{code}").text)

    def tache(url, corps):
        r = jx(c, url, corps, f"/projets/{code}")
        assert r.status_code == 200, r.text
        tid = r.json()["tache"]
        for _ in range(240):
            p = c.get(f"/taches/{tid}/progression").json()
            if not p["actif"]:
                return tid, p
            time.sleep(0.5)
        raise AssertionError("tâche trop longue")

    avant = len(squash.store["testCases"])
    sim, p = tache(f"/projets/{code}/squash/simuler", {"squash_id": "28", "squash_nom": "SauceDemo"})
    assert p["statut"] == "termine", p
    _, p = tache(f"/projets/{code}/squash/publier", {"simulation": sim})
    assert p["statut"] == "termine" and p["crees"] > 0, p
    assert len(squash.store["testCases"]) > avant
    corr = json.loads((d / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
    assert corr["squash_url"] == squash.url

    # La même personne se connecte à une autre instance Squash : l'envoi est refusé, rien n'y est créé
    autre = FauxSquash()
    try:
        regler_squash(c, adresse(autre))
        assert connexions.lire(__import__("app.main", fromlist=["base"]).base, uid)["url"] == autre.url
        _, p = tache(f"/projets/{code}/squash/simuler", {})
        assert p["statut"] == "echec" and "autre instance Squash" in p["erreur"], p
        assert not autre.store["testCases"] and not autre.store["requirements"]
    finally:
        autre.arreter()


def test_garde_reseau_a_la_connexion(espace, monkeypatch):
    """Même si le contrôle préalable est contourné (nom qui change de réponse entre le contrôle et
    la connexion), le module Squash refuse de se connecter à une adresse interne."""
    from app import connexions
    from app.config import reglages
    monkeypatch.setattr(reglages, "squash_reseau_prive", False)
    monkeypatch.setattr(connexions, "verifier_reseau", lambda url: None)  # contrôle préalable « trompé »
    c, squash = espace["client"], espace["squash"]
    uid = creer("hugo")
    connecter(c, "hugo", MDP)
    avant = len(squash.authentifications)
    page = html.unescape(regler_squash(c, adresse(squash).replace("127.0.0.1", "localhost"), mode="jeton", secret=JETON).text)
    assert "réseau interne" in page and "Connexion non enregistrée" in page, page[-2000:]
    assert len(squash.authentifications) == avant  # aucune requête n'est partie vers Squash
    assert connexion_de(uid) is None


def test_arret_d_un_envoi_en_cours(espace):
    """« Arrêter l'envoi » arrête la publication avant l'élément suivant ; une relance reprend sans doublon."""
    import shutil
    import time

    c, squash, racine = espace["client"], espace["squash"], espace["racine"]
    code = "boutique-arret"
    d = racine / "projets" / code
    shutil.copytree(racine / "projets" / "saucedemo", d)
    for f in (d / "02-a-valider").iterdir():
        if f.name != "LISEZMOI.md":
            shutil.move(str(f), str(d / "03-valide" / f.name))
    creer("lea")
    connecter(c, "lea", MDP)
    regler_squash(c, adresse(squash), mode="jeton", secret=JETON)

    def lancer(url, corps):
        r = jx(c, url, corps, f"/projets/{code}")
        assert r.status_code == 200, r.text
        return r.json()["tache"]

    def attendre(tid):
        for _ in range(600):
            p = c.get(f"/taches/{tid}/progression").json()
            if not p["actif"]:
                return p
            time.sleep(0.25)
        raise AssertionError("tâche trop longue")

    deja = len(squash.store["testCases"])
    # Projet Squash n° 29 : les autres tests publient les mêmes références (CT0001...) dans le n° 28.
    sim = lancer(f"/projets/{code}/squash/simuler", {"squash_id": "29", "squash_nom": "Autre projet"})
    assert attendre(sim)["statut"] == "termine"
    squash.lenteur_creation = 0.3
    try:
        tid = lancer(f"/projets/{code}/squash/publier", {"simulation": sim})
        for _ in range(200):
            if len(squash.store["reqFolders"]) + len(squash.store["requirements"]) >= 2:
                break
            time.sleep(0.1)
        assert jx(c, f"/taches/{tid}/arreter", {}, f"/projets/{code}").status_code == 200
        p = attendre(tid)
    finally:
        squash.lenteur_creation = 0
    assert p["statut"] == "annule", p
    assert "Envoi arrêté" in p["erreur"] and "sans doublon" in p["erreur"], p
    assert len(squash.store["testCases"]) - deja < 5  # arrêté bien avant la fin

    sim = lancer(f"/projets/{code}/squash/simuler", {})
    assert attendre(sim)["statut"] == "termine"
    p = attendre(lancer(f"/projets/{code}/squash/publier", {"simulation": sim}))
    assert p["statut"] == "termine", p
    # Chaque cas n'existe qu'une fois dans Squash : la reprise n'a rien recréé.
    corr = json.loads((d / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
    ids = list(corr["cas_de_tests"].values())
    assert ids and len(ids) == len(set(ids)) and all(i in squash.store["testCases"] for i in ids)
    assert len(squash.store["testCases"]) - deja == len(ids)
