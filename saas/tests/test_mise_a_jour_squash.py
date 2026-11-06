# -*- coding: utf-8 -*-
"""Temps B, lot 2 : mise à jour dans Squash des éléments créés par QA Factory, sans doublon.

Rien n'est réécrit ni supprimé : un élément changé dans QA Factory reçoit une nouvelle version (CT0001.1) et
l'ancienne passe en Obsolète. Un changement fait dans Squash par quelqu'un est conservé (recopié dans la nouvelle
version) ; un champ changé des deux côtés garde la version Squash, sauf si la personne choisit de la remplacer.
cd saas && python -m pytest -q tests/test_mise_a_jour_squash.py
"""
import html
import json
import shutil
import time

from conftest import connecter, jx, regler_squash
from faux_squash import JETON
from test_parametres import MDP, adresse, creer


def test_mise_a_jour_des_elements_crees_par_qa_factory(espace, request):
    from app import projets
    c, squash, racine = espace["client"], espace["squash"], espace["racine"]
    code = "boutique-maj"
    d = racine / "projets" / code
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(racine / "projets" / "saucedemo", d)
    for f in (d / "02-a-valider").iterdir():
        if f.name != "LISEZMOI.md":
            shutil.move(str(f), str(d / "03-valide" / f.name))
    # Projet Squash dédié : les autres tests publient les mêmes références ailleurs
    squash.store["projects"][31] = {"_type": "project", "id": 31, "name": "Boutique MAJ"}
    request.addfinalizer(lambda: squash.store["projects"].pop(31, None))  # les autres tests comptent les projets visibles
    creer("maj-iris")
    connecter(c, "maj-iris", MDP)
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
            time.sleep(0.2)
        raise AssertionError("tâche trop longue")

    def envoyer(premier=False, forcer=None):
        sim = lancer(f"/projets/{code}/squash/simuler", {"squash_id": "31", "squash_nom": "Boutique MAJ"} if premier else {})
        s = attendre(sim)
        assert s["statut"] == "termine", s
        corps = {"simulation": sim}
        if forcer is not None:
            corps["forcer"] = forcer
        p = attendre(lancer(f"/projets/{code}/squash/publier", corps))
        assert p["statut"] == "termine", p.get("erreur")
        return s, p

    # Premier envoi : tout est créé, puis Squash est à jour
    envoyer(premier=True)
    lire_corr = lambda: json.loads((d / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))  # noqa: E731
    corr = lire_corr()
    ids = dict(corr["cas_de_tests"])
    # Tout est rangé dans un dossier propre à QA Factory : le reste du projet Squash n'est pas touché
    racine = corr["dossier_racine"]
    assert racine["nom"] == "QA Factory - SauceDemo"
    assert squash.store["tcFolders"][racine["cas"]]["parent"] == {"_type": "project", "id": 31}
    assert all(squash.store["tcFolders"][i]["parent"] == {"_type": "test-case-folder", "id": racine["cas"]} for i in corr["dossiers_cas"].values())
    nb_cas = len(squash.store["testCases"])
    assert projets.a_mettre_a_jour(code) == []
    page = html.unescape(c.get(f"/projets/{code}").text)
    assert "Squash est à jour avec les cas validés." in page and "Vérifier Squash" in page

    a, b, k = sorted(ids)[:3]
    # Dans QA Factory : la dernière étape de a corrigée (ex. après les tests de l'application), le titre de b changé
    f = d / "03-valide" / "cas-de-tests.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    cas = {x["id"]: x for x in data["cas_de_tests"]}
    cas[a]["etapes"][-1]["resultat_attendu"] = "Libellé réel observé sur l'application."
    cas[b]["titre"] = "Titre revu dans QA Factory"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    projets.script("rendre_revue.py", code, "--dossier", "03-valide", "--forcer")  # comme l'application des corrections
    # Dans Squash, par une personne : le prérequis de k réécrit, et le titre de b changé lui aussi
    squash.store["testCases"][ids[k]]["prerequisite"] = "<p>Prérequis précisé par l'équipe dans Squash.</p>"
    squash.store["testCases"][ids[b]]["name"] = "Titre revu dans Squash"

    assert sorted(projets.a_mettre_a_jour(code)) == sorted([a, b])
    page = html.unescape(c.get(f"/projets/{code}").text)
    assert "2 éléments modifiés depuis le dernier envoi" in page and "Mettre à jour Squash" in page

    # Vérification : ce qui sera fait, ce qui est conservé, le conflit à trancher
    sim = lancer(f"/projets/{code}/squash/simuler", {})
    s = attendre(sim)
    assert s["statut"] == "termine", s["erreur"]
    det = {x["id"]: x for x in s["simulation"]["details"]}
    assert det[a]["action"] == "modifier" and det[a]["champs"] == ["étapes"] and det[a]["version"] == f"{a}.1"
    assert det[k]["action"] == "existe" and det[k]["conserves"] == ["prérequis"]
    assert det[b]["action"] == "conflit" and det[b]["version"] == f"{b}.1"
    assert [(x["libelle"], x["squash"], x["fichier"]) for x in det[b]["conflits"]] == [("titre", "Titre revu dans Squash", "Titre revu dans QA Factory")]
    assert s["simulation"]["resume"]["creer"] == 0

    # Un « remplacer » qui n'est pas un conflit de cette vérification est refusé
    assert jx(c, f"/projets/{code}/squash/publier", {"simulation": sim, "forcer": [a]}, f"/projets/{code}").status_code == 400
    # La personne choisit la version QA Factory pour b
    p = attendre(lancer(f"/projets/{code}/squash/publier", {"simulation": sim, "forcer": [b]}))
    assert p["statut"] == "termine", p.get("erreur")
    assert p["crees"] == 0 and p["modifies"] == 2

    nouveaux = lire_corr()["cas_de_tests"]
    tc_a, tc_b, tc_k = (squash.store["testCases"][nouveaux[x]] for x in (a, b, k))
    assert (tc_a["reference"], tc_b["reference"], tc_k["reference"]) == (f"{a}.1", f"{b}.1", k)
    assert "Libellé réel observé" in tc_a["steps"][-1]["expected_result"]
    assert tc_b["name"] == f"Titre revu dans QA Factory ({b}.1)"
    # Titre inchangé : la nouvelle version porte le suffixe (Squash refuse deux cas de même nom dans un dossier)
    assert tc_a["name"] == f"{squash.store['testCases'][ids[a]]['name']} ({a}.1)"
    assert "précisé par l'équipe" in tc_k["prerequisite"] and nouveaux[k] == ids[k]
    # Les anciennes versions restent, inchangées, en Obsolète, dans le même dossier
    for x in (a, b):
        ancien = squash.store["testCases"][ids[x]]
        assert ancien["status"] == "OBSOLETE" and ancien["reference"] == x
        assert squash.store["testCases"][nouveaux[x]]["parent"] == ancien["parent"]
    assert squash.store["testCases"][ids[b]]["name"] == "Titre revu dans Squash"
    assert len(squash.store["testCases"]) == nb_cas + 2  # deux nouvelles versions, aucun doublon
    assert not any(m == "DELETE" for m, *_ in squash.requetes)
    assert projets.a_mettre_a_jour(code) == []
    journal = (d / "journal.md").read_text(encoding="utf-8")
    assert "2 mis à jour dans Squash" in journal and f"1 conflit(s) remplacé(s) : {b}" in journal
    assert f"nouvelles versions : {a}.1, {b}.1" in journal

    # Le tour suivant ne réécrit rien ; le changement de l'équipe reste conservé
    ecritures = sum(1 for m, *_ in squash.requetes if m != "GET")
    s, p = envoyer()
    assert p["crees"] == 0 and p["modifies"] == 0
    assert sum(1 for m, *_ in squash.requetes if m != "GET") == ecritures
    assert "précisé par l'équipe" in tc_k["prerequisite"]
