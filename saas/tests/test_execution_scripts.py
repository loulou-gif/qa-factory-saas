# -*- coding: utf-8 -*-
"""Temps B, lot 4 : exécution des scripts Playwright depuis l'application (sans IA), contrôle des scripts,
retrait des secrets des rapports, rapport Playwright, inventaire et archive.

Playwright est remplacé par un faux lanceur (même interface : cli.js test, rapports JSON et HTML, sortie « list »),
pour tester toute la chaîne sans navigateur ni réseau. Un essai réel sur SauceDemo se lance à la demande :
QAF_ESSAI_PLAYWRIGHT=<dossier contenant node_modules/@playwright/test> python -m pytest -q tests/test_execution_scripts.py
"""
import base64
import html
import io
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import pytest

from conftest import connecter, jx
from test_automatisation import REF, projet_neuf
from test_parametres import MDP, creer
from test_tests_application import poster

SECRET = "mdp-tres-secret-42"

# Faux @playwright/test : lit les titres [CT…] des specs, applique --grep, écrit les rapports comme Playwright.
FAUX_CLI = r"""
const fs = require('fs'), path = require('path');
const args = process.argv.slice(2);
const grep = new RegExp(args[args.indexOf('--grep') + 1]);
const tests = [];
(function lire(d) {
  for (const n of fs.readdirSync(d)) {
    const p = path.join(d, n);
    if (fs.statSync(p).isDirectory()) lire(p);
    else if (/\.spec\.[jt]s$/.test(n)) {
      const t = fs.readFileSync(p, 'utf8'); const re = /test\(\s*['"`](\[CT\d+\][^'"`]*)['"`]/g; let m;
      while ((m = re.exec(t))) if (grep.test(m[1])) tests.push({ titre: m[1], fichier: path.relative('tests', p).replace(/\\/g, '/') });
    }
  }
})('tests');
const statut = (t) => t.includes('CT0001') ? 'expected' : (t.includes('CT0002') ? 'unexpected' : 'flaky');
const resultat = (s) => ({ status: s, duration: 1200, errors: s === 'passed' ? [] : [{ message: 'Error: attendu « Products », reçu « ' + process.env.COMPTE_1_MOT_DE_PASSE + ' »' }] });
const specs = tests.map((t, i) => ({ title: t.titre, file: t.fichier, line: 6 + i, tests: [{ status: statut(t.titre),
  results: statut(t.titre) === 'expected' ? [resultat('passed')] : (statut(t.titre) === 'flaky' ? [resultat('failed'), resultat('passed')] : [resultat('failed'), resultat('failed')]) }] }));
fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE, JSON.stringify({ suites: [{ title: 'x', specs }], errors: [] }));
fs.mkdirSync(path.join(process.env.PLAYWRIGHT_HTML_OUTPUT_DIR, 'data'), { recursive: true });
fs.writeFileSync(path.join(process.env.PLAYWRIGHT_HTML_OUTPUT_DIR, 'index.html'),
  '<!doctype html><title>Playwright</title><p>Fill "' + process.env.COMPTE_1_MOT_DE_PASSE + '"</p>');
fs.writeFileSync(path.join(process.env.PLAYWRIGHT_HTML_OUTPUT_DIR, 'data', 'piece.html'), '<script>alert(1)</script>');
fs.writeFileSync(path.join(process.env.PLAYWRIGHT_HTML_OUTPUT_DIR, 'data', 'capture.png'), 'png');
// Environnement reçu : rien du serveur
fs.writeFileSync(path.join(path.dirname(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE), 'env.json'), JSON.stringify(Object.keys(process.env)));
tests.forEach((t, i) => console.log(`  ${statut(t.titre) === 'unexpected' ? 'x' : 'ok'} ${i + 1} [chromium] › ${t.fichier} › ${t.titre} (1.2s)`));
process.exit(tests.some((t) => statut(t.titre) === 'unexpected') ? 1 : 0);
"""


@pytest.fixture()
def faux_playwright(tmp_path, monkeypatch):
    cli = tmp_path / "pw" / "node_modules" / "@playwright" / "test" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text(FAUX_CLI, encoding="utf-8")
    monkeypatch.setenv("QAF_PLAYWRIGHT_DIR", str(tmp_path / "pw"))
    return tmp_path / "pw"


def depot_genere(racine, code):
    """Projet avec un dépôt JavaScript et les trois scripts de référence (CT0001 à CT0003)."""
    import automatisation as auto
    d = projet_neuf(racine, code)
    g = auto.preparer(code, ["CT0001", "CT0002", "CT0003"], "js", "https://www.saucedemo.com", ["Client"])
    ref = racine.joinpath(*REF)
    shutil.copytree(ref / "depot", d / "05-automatisation", dirs_exist_ok=True)
    shutil.copytree(ref / "resultats", g / "resultats", dirs_exist_ok=True)
    auto.consolider(code, g.name)
    return d


def test_controle_des_scripts(espace):
    import execution_scripts as ex
    racine = espace["racine"]
    d = depot_genere(racine, "exec-controle")
    depot = d / "05-automatisation"
    hotes = ex.hotes_autorises("https://www.saucedemo.com/", ["https://sso.saucedemo.com"])
    assert hotes == ["www.saucedemo.com", "sso.saucedemo.com"]
    assert ex.controler(depot, hotes) == []

    page = depot / "pages" / "authentification.page.js"
    propre = page.read_text(encoding="utf-8")
    interdits = {
        "const fs = require('fs');": "module « fs » non autorisé",
        "const { execSync } = require('child_process');": "module système",
        "const x = process.env.QAF_SECRET;": "accès à process",
        "await fetch('https://www.saucedemo.com/x');": "requête réseau",
        "const m = require(nom);": "require d'un nom calculé",
        "const m = await import('./autre');": "import dynamique",
        "eval('1');": "code construit",
        "test('[CT0009] x', async ({ request }) => {});": "fixture request",
        "test.use({ launchOptions: { args: [] } });": "navigateur lancé ou réglé",
        "await page.goto('https://collecte.exemple.net/?d=1');": "adresse hors de l'application (collecte.exemple.net)",
        "const u = require('../config/autre');": "module « ../config/autre » non autorisé",
    }
    for code, attendu in interdits.items():
        page.write_text(propre + "\n" + code + "\n", encoding="utf-8")
        problemes = ex.controler(depot, hotes)
        assert any(attendu in p for p in problemes), (code, problemes)
    # Adresse autorisée et fichiers du dépôt : acceptés
    page.write_text(propre + "\nconst ref = 'https://sso.saucedemo.com/login';\nconst u = require('../utils/unique');\n", encoding="utf-8")
    assert ex.controler(depot, hotes) == []
    page.write_text(propre, encoding="utf-8")

    # node_modules ou configuration ajoutés : refusés
    (depot / "tests" / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    (depot / "tests" / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    problemes = ex.controler(depot, hotes)
    assert any("node_modules" in p for p in problemes) and any("tests/package.json" in p for p in problemes)
    shutil.rmtree(depot / "tests" / "node_modules")
    (depot / "tests" / "package.json").unlink()

    # Fichiers du gabarit modifiés : rétablis ; .env supprimé
    config = depot / "playwright.config.js"
    config.write_text("module.exports = { globalSetup: './evil.js' };", encoding="utf-8")
    (depot / ".env").write_text("NODE_OPTIONS=--require ./evil.js", encoding="utf-8")
    retablis = ex.retablir_gabarit(depot, "js")
    assert "playwright.config.js" in retablis and ".env (supprimé)" in retablis
    assert "QAF_HOTES_AUTORISES" in config.read_text(encoding="utf-8") and not (depot / ".env").exists()
    assert ex.retablir_gabarit(depot, "js") == []


def test_nettoyage_du_rapport_html(tmp_path):
    import execution_scripts as ex
    donnees = io.BytesIO()
    with zipfile.ZipFile(donnees, "w") as z:
        z.writestr("test.json", json.dumps({"title": f'Fill "{SECRET}"', "autre": 'mot "de" passe'}))
        z.writestr("report.json", "{}")
    index = tmp_path / "rapport" / "index.html"
    index.parent.mkdir()
    index.write_text('<html><template id="playwrightReportBase64">data:application/zip;base64,'
                     + base64.b64encode(donnees.getvalue()).decode() + "</template></html>", encoding="utf-8")
    (tmp_path / "sortie.txt").write_text(f"Erreur : {SECRET} et {json.dumps(SECRET)}", encoding="utf-8")
    ex.nettoyer_dossier(tmp_path, [SECRET, 'mot "de" passe', "abc"])
    texte = index.read_text(encoding="utf-8")
    contenu = base64.b64decode(texte.split("base64,")[1].split("</template>")[0])
    z = zipfile.ZipFile(io.BytesIO(contenu))
    t = z.read("test.json").decode()
    assert SECRET not in t and "<secret retiré>" in t and "de\\\" passe" not in t
    assert SECRET not in (tmp_path / "sortie.txt").read_text(encoding="utf-8")


def test_execution_depuis_l_application(espace, faux_playwright):
    import execution_scripts as ex
    c, racine = espace["client"], espace["racine"]
    code = "exec-scripts"
    d = depot_genere(racine, code)
    creer("lou")
    connecter(c, "lou", MDP)
    page = f"/projets/{code}/application"
    poster(c, page, {"url": "https://www.saucedemo.com", "actions": "lecture-seule", "domaines": ""}, page)
    poster(c, page + "/comptes", {"libelle": "Client", "identifiant": "standard_user", "mot_de_passe": SECRET}, page)

    # Page : section d'exécution, scripts jamais exécutés
    t = html.unescape(c.get(f"/projets/{code}/automatisation").text)
    assert "Exécuter les 3 scripts" in t and "pas encore été exécutés" in t and "Télécharger les scripts (.zip)" in t

    # Lancement et suivi
    assert jx(c, f"/projets/{code}/executer-scripts", {"cas": ["CT0099"]}, f"/projets/{code}").status_code == 400
    r = jx(c, f"/projets/{code}/executer-scripts", {}, f"/projets/{code}")
    assert r.status_code == 200, r.text
    tid = r.json()["tache"]
    for _ in range(200):
        p = c.get(f"/taches/{tid}/progression").json()
        if not p["actif"]:
            break
        time.sleep(0.2)
    assert p["statut"] == "termine", p
    e = ex.dossier_execution(d, p["execution"])
    s = json.loads((e / "synthese.json").read_text(encoding="utf-8"))
    r = {x["id"]: x for x in s["resultats"]}
    assert s["statistiques"] == {"reussi": 1, "echoue": 1, "instable": 1, "ignore": 0, "non_execute": 0, "total": 3}
    assert r["CT0002"]["statut"] == "echoue" and r["CT0002"]["essais"] == 2 and "Products" in r["CT0002"]["erreur"]
    assert r["CT0003"]["statut"] == "instable" and "second" in r["CT0003"]["remarque"]

    # Environnement du lanceur : URL, comptes, restriction réseau ; rien des secrets du serveur
    env = json.loads((e / "env.json").read_text(encoding="utf-8"))
    assert {"BASE_URL", "COMPTE_1_IDENTIFIANT", "COMPTE_1_MOT_DE_PASSE", "QAF_HOTES_AUTORISES", "CI"} <= set(env)
    assert not [k for k in env if k.startswith(("QAF_SECRET", "QAF_CLE", "QAF_ADMIN", "OPENCODE", "SQUASH"))]

    # Aucun secret dans les fichiers de l'exécution, ni dans la page
    for f in e.rglob("*"):
        if f.is_file():
            assert SECRET not in f.read_text(encoding="utf-8", errors="replace"), f
    t = html.unescape(c.get(f"/projets/{code}/automatisation").text)
    assert SECRET not in t
    assert "1 réussi" in t and "1 échoué" in t and "1 instable" in t and "Ouvrir le rapport Playwright" in t
    assert "<secret retiré>" in t  # dans le message d'erreur de CT0002

    # Rapport Playwright : index.html affiché ; pièce jointe HTML téléchargée dans un bac à sable ; pas de sortie du dossier
    base_rapport = f"/projets/{code}/automatisation/executions/{e.name}/rapport"
    r = c.get(base_rapport + "/index.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and SECRET not in r.text
    r = c.get(base_rapport + "/data/piece.html")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "sandbox" in r.headers["content-security-policy"]
    assert c.get(base_rapport + "/data/capture.png").headers["content-type"] == "image/png"
    assert c.get(base_rapport + "/../synthese.json").status_code == 404
    assert c.get(f"/projets/{code}/automatisation/executions/..%2F..%2F03-valide/rapport/index.html").status_code == 404

    # Inventaire : dernier statut de chaque test ; page du projet : résumé
    inventaire = (d / "05-automatisation" / "docs" / "test-inventory.md").read_text(encoding="utf-8")
    assert "| PASSED |" in inventaire and "| FAILED |" in inventaire and "| FLAKY |" in inventaire
    assert "Dernière exécution le" in html.unescape(c.get(f"/projets/{code}").text)

    # Archive : le dépôt sans .env ni résultats, avec son mode d'emploi
    (d / "05-automatisation" / ".env").write_text(f"COMPTE_1_MOT_DE_PASSE={SECRET}", encoding="utf-8")
    r = c.get(f"/projets/{code}/automatisation/archive")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    noms = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    racine_zip = f"{code}-automatisation/"
    assert racine_zip + "tests/authentification/authentification.spec.js" in noms and racine_zip + "README.md" in noms
    assert racine_zip + ".env.example" in noms and racine_zip + ".env" not in noms
    assert not [n for n in noms if "test-results" in n or "node_modules" in n]

    # Script qui sort du navigateur : exécution refusée, avec la raison
    pagejs = d / "05-automatisation" / "pages" / "authentification.page.js"
    pagejs.write_text(pagejs.read_text(encoding="utf-8") + "\nconst fs = require('fs');\n", encoding="utf-8")
    tid = jx(c, f"/projets/{code}/executer-scripts", {}, f"/projets/{code}").json()["tache"]
    for _ in range(100):
        p = c.get(f"/taches/{tid}/progression").json()
        if not p["actif"]:
            break
        time.sleep(0.2)
    assert p["statut"] == "echec" and "Exécution refusée" in p["erreur"] and "« fs »" in p["erreur"], p
    assert not (d / "05-automatisation" / ".env").exists()  # supprimé avant le contrôle

    # Playwright absent du serveur : lancement refusé avec un message clair
    os.environ["QAF_PLAYWRIGHT_DIR"] = str(faux_playwright / "absent")
    r = jx(c, f"/projets/{code}/executer-scripts", {}, f"/projets/{code}")
    assert r.status_code == 503 and "Playwright n'est pas installé" in r.text


@pytest.mark.skipif(not os.environ.get("QAF_ESSAI_PLAYWRIGHT"), reason="essai réel sur SauceDemo : QAF_ESSAI_PLAYWRIGHT=<dossier Playwright>")
def test_execution_reelle_saucedemo(espace, monkeypatch):
    import execution_scripts as ex
    monkeypatch.setenv("QAF_PLAYWRIGHT_DIR", os.environ["QAF_ESSAI_PLAYWRIGHT"])
    code = "exec-reel"
    depot_genere(espace["racine"], code)
    e = ex.preparer(code, [], "https://www.saucedemo.com/")
    s = ex.executer(code, e.name, "https://www.saucedemo.com/",
                    secrets={"COMPTE_1_IDENTIFIANT": "standard_user", "COMPTE_1_MOT_DE_PASSE": "secret_sauce"})
    assert s["statistiques"]["reussi"] == 3, s
    texte = (e / "rapport" / "index.html").read_text(encoding="utf-8")
    donnees = zipfile.ZipFile(io.BytesIO(base64.b64decode(ex.RE_DONNEES_RAPPORT.search(texte).group(2))))
    assert s["rapport"] and not [n for n in donnees.namelist() if "secret_sauce" in donnees.read(n).decode("utf-8", "replace")]
    assert any("<secret retiré>" in donnees.read(n).decode("utf-8", "replace") for n in donnees.namelist())
    assert not Path(e / "test-results").exists()
