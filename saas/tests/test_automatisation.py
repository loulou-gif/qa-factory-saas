# -*- coding: utf-8 -*-
"""Temps B, lot 3 : priorités d'automatisation, dépôt Playwright JS/TS par projet, tâche « automatiser »,
contrôle des scripts écrits et inventaire.

Le moteur IA est remplacé par un faux agent (il recopie les scripts de référence de SauceDemo) :
cd saas && python -m pytest -q tests/test_automatisation.py
"""
import html
import json
import re
import shutil
import time

from conftest import connecter, jx
from test_parametres import MDP, creer
from test_tests_application import poster, projet_valide

REF = ("projets", "saucedemo", "04-livrables", "automatisation-reference")


def projet_neuf(racine, code):
    """Projet validé sans tests ni automatisation (la copie de travail de saucedemo peut contenir des essais)."""
    d = projet_valide(racine, code)
    for x in ("04-livrables/execution", "04-livrables/automatisation", "05-automatisation"):
        shutil.rmtree(d / x, ignore_errors=True)
    return d


def campagne_de_reference(racine, code):
    """Dernière campagne de tests consolidée avec les résultats de référence (26 réussis, CT0027 échoué)."""
    import execution
    c = execution.preparer(code, "https://www.saucedemo.com", ["Client"])
    ref = racine / "projets" / "saucedemo" / "04-livrables" / "execution-reference"
    shutil.copytree(ref / "resultats", c / "resultats", dirs_exist_ok=True)
    shutil.copytree(ref / "captures", c / "captures", dirs_exist_ok=True)
    execution.consolider(code, c.name)
    return c


def test_priorites(espace):
    import automatisation as outil
    racine = espace["racine"]
    code = "auto-priorites"
    d = projet_neuf(racine, code)

    # Sans tests lancés : classement sur la criticité, l'usage et le coût ; rien de déconseillé
    p = outil.priorites(code)
    assert len(p["cas"]) == 27 and p["tests_du"] == "" and p["langage"] == "" and p["automatises"] == 0
    ct1 = next(c for c in p["cas"] if c["id"] == "CT0001")
    assert ct1["niveau"] == "prioritaire" and ct1["coche"] and "parcours nominal, le plus utilisé" in ct1["raisons"]
    notes = [c["note"] for c in p["cas"] if c["niveau"] == "prioritaire"]
    assert notes == sorted(notes, reverse=True)

    # Après une campagne : stabilité observée, cas échoué signalé, correction en attente signalée
    campagne_de_reference(racine, code)
    p = outil.priorites(code)
    assert p["tests_du"]
    ct1 = next(c for c in p["cas"] if c["id"] == "CT0001")
    assert "réussi aux derniers tests : comportement stable" in ct1["raisons"]
    ct27 = next(c for c in p["cas"] if c["id"] == "CT0027")
    assert any("échoué aux derniers tests" in a for a in ct27["alertes"])
    ct2 = next(c for c in p["cas"] if c["id"] == "CT0002")
    assert any("correction du cas proposée" in a for a in ct2["alertes"])

    # Un cas bloqué aux derniers tests, ou d'un type mal vérifié par Playwright, est déconseillé et non coché
    data = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
    next(c for c in data["cas_de_tests"] if c["id"] == "CT0004")["type_test"] = "performance"
    (d / "03-valide" / "cas-de-tests.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ct4 = next(c for c in outil.priorites(code)["cas"] if c["id"] == "CT0004")
    assert ct4["niveau"] == "deconseille" and not ct4["coche"] and "performance" in ct4["deconseille"]


def test_depot_typescript_et_erreur_de_syntaxe(espace):
    import automatisation as outil
    racine = espace["racine"]
    code = "auto-ts"
    d = projet_neuf(racine, code)
    g = outil.preparer(code, ["CT0001", "CT0002"], "ts", "https://www.saucedemo.com", ["Client", "Administrateur"])
    depot = d / "05-automatisation"
    for f in ("playwright.config.ts", "config/env.ts", "utils/evidence.ts", "utils/unique.ts", "tsconfig.json",
              "utils/evidence-reporter.js", "agents/features/authentification.md"):
        assert (depot / f).exists(), f
    for f in ("playwright.config.js", "config/env.js", "utils/evidence.js", "utils/unique.js"):
        assert not (depot / f).exists(), f
    assert '"typescript"' in (depot / "package.json").read_text(encoding="utf-8")
    agents = (depot / "agents" / "AGENTS.md").read_text(encoding="utf-8")
    assert "TypeScript" in agents and not re.search(r"\{\{[A-Z_]+\}\}", agents) and "Remplacer les marqueurs" not in agents and "spec.ts" in agents
    exemple = (depot / ".env.example").read_text(encoding="utf-8")
    assert "COMPTE_2_MOT_DE_PASSE=" in exemple and "Administrateur" in exemple
    gen = json.loads((g / "generation.json").read_text(encoding="utf-8"))
    assert gen["langage"] == "ts" and gen["cas"][0]["test"] == "tests/authentification/authentification.spec.ts"
    assert json.loads((d / "projet.json").read_text(encoding="utf-8"))["automatisation"]["langage"] == "ts"
    # Un dépôt garde son langage
    try:
        outil.preparer(code, ["CT0003"], "js")
        assert False, "changement de langage accepté"
    except outil.ErreurAutomatisation as e:
        assert "TypeScript" in str(e)

    # Consolidation : test trouvé par son titre, JSON de données invalide signalé
    (depot / "tests" / "authentification").mkdir(parents=True)
    (depot / "tests" / "authentification" / "authentification.spec.ts").write_text(
        "import { test } from '@playwright/test';\ntest('[CT0001] Se connecter avec un compte valide @authentification', async () => {});\n",
        encoding="utf-8")
    (depot / "data").mkdir(exist_ok=True)
    (depot / "data" / "authentification.json").write_text("{pas du json", encoding="utf-8")
    s = outil.consolider(code, g.name)
    r = {x["id"]: x for x in s["resultats"]}
    assert r["CT0001"]["statut"] == "genere" and r["CT0002"]["statut"] == "non_genere"
    assert any("data/authentification.json" in a and "JSON invalide" in a for a in s["avertissements"])

    # JavaScript : une erreur de syntaxe rend le script « non généré »
    code = "auto-js-syntaxe"
    d = projet_neuf(racine, code)
    g = outil.preparer(code, ["CT0001"], "js")
    t = d / "05-automatisation" / "tests" / "authentification"
    t.mkdir(parents=True)
    (t / "authentification.spec.js").write_text("test('[CT0001] Se connecter', async () => {\n", encoding="utf-8")
    s = outil.consolider(code, g.name)
    if shutil.which("node"):
        assert s["resultats"][0]["statut"] == "non_genere" and "Erreur de syntaxe" in s["resultats"][0]["remarque"]


def test_generation_complete(espace, monkeypatch):
    from app import moteur as module_moteur
    from app.config import reglages
    c, racine = espace["client"], espace["racine"]
    code = "auto-generation"
    d = projet_neuf(racine, code)
    creer("pia")
    connecter(c, "pia", MDP)
    page = f"/projets/{code}/application"

    # Sans lien : pas d'encart Automatiser, lancement refusé
    assert "Choisir les scénarios à automatiser" not in html.unescape(c.get(f"/projets/{code}").text)
    assert jx(c, f"/projets/{code}/automatiser", {"cas": ["CT0001"]}, f"/projets/{code}").status_code == 409
    poster(c, page, {"url": "https://www.saucedemo.com", "actions": "lecture-seule", "domaines": ""}, page)
    poster(c, page + "/comptes", {"libelle": "Client", "identifiant": "standard_user", "mot_de_passe": "secret_sauce"}, page)
    assert "Choisir les scénarios à automatiser" in html.unescape(c.get(f"/projets/{code}").text)

    # Page de choix : classement, cas prioritaires cochés, JavaScript par défaut
    t = html.unescape(c.get(f"/projets/{code}/automatisation").text)
    assert "Prioritaires" in t and "CT0001" in t and 'value="js" checked' in t and "Générer les scripts" in t

    vu = {}
    m = module_moteur.moteur

    def executer(base_, tid, commande, arguments, outils=None, modele=None, secours=None):
        vu["commande"] = (commande, arguments, outils)
        ident = arguments.split()[-1]
        g = d / "04-livrables" / "automatisation" / ident
        vu["generation"] = json.loads((g / "generation.json").read_text(encoding="utf-8"))
        ref = racine.joinpath(*REF)
        shutil.copytree(ref / "depot", d / "05-automatisation", dirs_exist_ok=True)
        shutil.copytree(ref / "resultats", g / "resultats", dirs_exist_ok=True)
        # Un secret écrit par erreur dans les données doit être retiré
        (d / "05-automatisation" / "data").mkdir(exist_ok=True)
        (d / "05-automatisation" / "data" / "authentification.json").write_text('{"mdp": "secret_sauce"}', encoding="utf-8")
        return {"compte_rendu": "Fini.", "cout_usd": 0.31}

    monkeypatch.setattr(m, "disponible", lambda: (True, ""))
    monkeypatch.setattr(m, "ajouter_navigateur", lambda nom, config: vu.setdefault("navigateur", (nom, config)))
    monkeypatch.setattr(m, "retirer_navigateur", lambda nom: vu.setdefault("retire", nom))
    monkeypatch.setattr(m, "executer", executer)
    monkeypatch.setattr(reglages, "modele", "openrouter/fournisseur/modele")

    assert jx(c, f"/projets/{code}/automatiser", {"cas": ["CT9999"]}, f"/projets/{code}").status_code == 400
    assert jx(c, f"/projets/{code}/automatiser", {"cas": ["CT0001"], "langage": "python"}, f"/projets/{code}").status_code == 400
    r = jx(c, f"/projets/{code}/automatiser", {"cas": ["CT0001", "CT0002", "CT0003", "CT0005"], "langage": "js"}, f"/projets/{code}")
    assert r.status_code == 200, r.text
    tid = r.json()["tache"]
    for _ in range(120):
        p = c.get(f"/taches/{tid}/progression").json()
        if not p["actif"]:
            break
        time.sleep(0.25)
    assert p["statut"] == "termine", p
    assert p["generation"] == vu["generation"]["id"]

    # Navigateur de la tâche et fiche de génération : seulement les noms des secrets
    nom, config = vu["navigateur"]
    assert nom == f"nav{tid}" and vu["retire"] == nom
    assert json.loads(config["environment"]["QAF_NAV_SECRETS"])["COMPTE_1_MOT_DE_PASSE"] == "secret_sauce"
    commande, arguments, outils = vu["commande"]
    assert commande == "automatiser" and arguments == f"{code} generation {vu['generation']['id']}"
    assert outils == {"nav*": False, f"nav{tid}_*": True}
    gen_texte = json.dumps(vu["generation"])
    assert "secret_sauce" not in gen_texte and "standard_user" not in gen_texte and "COMPTE_1_MOT_DE_PASSE" in gen_texte
    assert vu["generation"]["depot"] == f"projets/{code}/05-automatisation" and vu["generation"]["langage"] == "js"

    # Dépôt : gabarit JavaScript complété, specs copiées, secret retiré, inventaire
    depot = d / "05-automatisation"
    agents = (depot / "agents" / "AGENTS.md").read_text(encoding="utf-8")
    assert not re.search(r"\{\{[A-Z_]+\}\}", agents) and "https://www.saucedemo.com" in agents and "JavaScript" in agents
    assert (depot / "playwright.config.js").exists() and (depot / "agents" / "features" / "authentification.md").exists()
    assert "secret_sauce" not in (depot / "data" / "authentification.json").read_text(encoding="utf-8")
    inventaire = (depot / "docs" / "test-inventory.md").read_text(encoding="utf-8")
    assert "| CT0001 |" in inventaire and "NOT_RUN" in inventaire and "CT0005" not in inventaire

    # Résultats affichés : 3 scripts écrits, CT0005 non généré, téléchargement d'un script
    t = html.unescape(c.get(f"/projets/{code}/automatisation").text)
    assert "3 scripts écrits" in t and "1 non généré" in t and "Aucun test [CT0005]" in t and "un secret y était écrit" in t
    assert "Déjà automatisé" in t and "le dépôt du projet est en javascript" in t.lower()
    assert c.get(f"/projets/{code}/telecharger/05-automatisation/tests/authentification/authentification.spec.js").status_code == 200
    assert c.get(f"/projets/{code}/telecharger/05-automatisation/.env.example").status_code == 404
    assert "3 scénarios automatisés en JavaScript" in html.unescape(c.get(f"/projets/{code}").text)

    # Le dépôt garde son langage ; le journal du projet garde la trace
    r = jx(c, f"/projets/{code}/automatiser", {"cas": ["CT0005"], "langage": "ts"}, f"/projets/{code}")
    assert r.status_code == 409 and "JavaScript" in r.text
    assert "automatiser" in (d / "journal.md").read_text(encoding="utf-8")
