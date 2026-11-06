# -*- coding: utf-8 -*-
"""Exécution des scripts Playwright du dépôt d'automatisation (temps B, lot 4), sans IA.

    python outils/execution_scripts.py controler <projet>
    python outils/execution_scripts.py executer <projet> [--cas CT0001,CT0002] --url <lien> [--secrets fichier.json]
    python outils/execution_scripts.py archive <projet> <fichier.zip>

Les scripts ont été écrits par l'assistant : avant de les lancer avec les comptes de test, on vérifie
qu'ils ne font que piloter le navigateur.
- Les fichiers du gabarit (configuration, utils/) sont rétablis à l'identique ; un fichier .env, un
  dossier node_modules ou une configuration (package.json, tsconfig…) ajoutés par l'assistant sont refusés.
- Les fichiers de pages/, tests/ et data/ n'importent que @playwright/test et des fichiers du dépôt ;
  pas d'accès à process, au réseau hors navigateur, à du code dynamique, ni d'adresse hors de l'application.
- Le navigateur ne résout que les domaines de l'application (QAF_HOTES_AUTORISES, lu par playwright.config).
- Le processus reçoit un environnement vide, sauf l'URL, les comptes de test et le nécessaire à Node.
- Traces désactivées ; tout secret est retiré des rapports (le rapport HTML de Playwright écrit les valeurs saisies).

Résultats : 04-livrables/automatisation/executions/<AAAAMMJJ-HHMMSS>/ (execution.json, synthese.json,
rapport/ = rapport HTML Playwright, resultats.json = rapport JSON, sortie.txt). L'inventaire du dépôt
(docs/test-inventory.md) reçoit le dernier statut de chaque test.

Playwright vient d'un dossier commun au serveur (QAF_PLAYWRIGHT_DIR, /opt/qaf-playwright dans l'image) :
@playwright/test, typescript, @types/node. Le dépôt n'a pas de node_modules.
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import automatisation as auto
from qa_commun import RACINE, charger_projet, journaliser

STATUTS = {"reussi": "Réussi", "echoue": "Échoué", "instable": "Instable", "ignore": "Ignoré", "non_execute": "Non exécuté"}
ETATS_PLAYWRIGHT = {"expected": "reussi", "unexpected": "echoue", "flaky": "instable", "skipped": "ignore"}
# Fichiers du gabarit rétablis avant chaque exécution (ce sont eux qui s'exécutent en premier).
GABARIT_EXECUTE = ("playwright.config.js", "playwright.config.ts", "tsconfig.json")
DOSSIERS_GABARIT = ("config", "utils")
DOSSIERS_SCRIPTS = ("pages", "tests", "data")
EXTENSIONS_CODE = {".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".mts", ".cts"}
CONFIGURATIONS_INTERDITES = re.compile(r"^(package\.json|tsconfig.*\.json|jsconfig\.json|\.babelrc.*|babel\.config\..*|\.env.*|\.npmrc)$", re.I)
MODULES_PERMIS = {"@playwright/test"}
OUTILS_PERMIS = {"config/env", "utils/evidence", "utils/unique"}
RE_MODULE = re.compile(r"""\brequire\s*\(\s*(['"`])([^'"`]*)\1\s*\)|\b(?:import|export)\b[^'"`;]*?\bfrom\s*(['"`])([^'"`]*)\3|\bimport\s*(['"`])([^'"`]*)\5""")
INTERDITS = [
    (re.compile(r"\bprocess\s*(\.|\[)"), "accès à process (environnement, système) : lire les comptes avec config/env"),
    (re.compile(r"\b(eval|Function)\s*\("), "exécution de code construit à la volée"),
    (re.compile(r"\bglobalThis\b|\bglobal\s*(\.|\[)"), "accès à l'objet global"),
    (re.compile(r"\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bEventSource\b|\bsendBeacon\b"), "requête réseau en dehors des pages"),
    (re.compile(r"\bimport\s*\("), "import dynamique"),
    (re.compile(r"""\brequire\s*\(\s*(?!['"`])"""), "require d'un nom calculé"),
    (re.compile(r"""\brequire\s*\.\s*(resolve|cache|main|extensions)\b|\bmodule\s*\.\s*(constructor|require|parent|children|paths)\b|__proto__|\bconstructor\s*\[|\[\s*['"`]constructor"""),
     "accès au chargeur de modules"),
    (re.compile(r"\b(chromium|firefox|webkit|_electron|_android)\s*\.\s*(launch|connect)|\bconnectOverCDP\b|\blaunchOptions\b|\bconnectOptions\b|\bproxy\s*:"),
     "navigateur lancé ou réglé hors de la configuration"),
    (re.compile(r"[{,]\s*request\s*[},:]|\brequest\s*\.\s*(get|post|put|patch|delete|head|fetch|newContext)\s*\(|\.request\s*\.\s*(get|post|put|patch|delete|head|fetch)\s*\("),
     "requête HTTP directe (fixture request) : non prise en charge"),
    (re.compile(r"\b(child_process|worker_threads|node:)"), "module système"),
]
RE_URL = re.compile(r"\b(?:https?|wss?|ftp)://([A-Za-z0-9.\-]+|\[[0-9a-fA-F:]+\])", re.I)
RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RE_LIGNE_TEST = re.compile(r"^\s*(ok|x|-|✓|✘|°)\s+\d+\s.*?\[(CT\d{4,})\]")
RE_TSC = re.compile(r"^(.+?)\((\d+),(\d+)\): error (TS(\d+)): (.*)$")
RE_DONNEES_RAPPORT = re.compile(r'(<template id="playwrightReportBase64">data:application/zip;base64,)([A-Za-z0-9+/=]+)(</template>)')
MAX_MESSAGE = 800


class ErreurExecutionScripts(Exception):
    pass


# ---------------------------------------------------------------- Playwright du serveur

def dossier_playwright() -> Path:
    return Path(os.environ.get("QAF_PLAYWRIGHT_DIR") or "/opt/qaf-playwright")


def playwright() -> tuple:
    """(node, cli.js de @playwright/test, node_modules) ; erreur claire si Playwright n'est pas installé sur le serveur."""
    node = shutil.which("node")
    modules = dossier_playwright() / "node_modules"
    cli = modules / "@playwright" / "test" / "cli.js"
    if not node:
        raise ErreurExecutionScripts("Node.js n'est pas installé sur le serveur.")
    if not cli.exists():
        raise ErreurExecutionScripts("Playwright n'est pas installé sur le serveur (QAF_PLAYWRIGHT_DIR). Prévenez l'administrateur.")
    return node, cli, modules


def disponible() -> tuple:
    try:
        playwright()
        return True, ""
    except ErreurExecutionScripts as e:
        return False, str(e)


def verifier_typescript(depot: Path) -> list:
    """Diagnostics de tsc --noEmit sur le dépôt : [{fichier, ligne, code, message, syntaxe}]."""
    node, _, modules = playwright()
    tsc = modules / "typescript" / "bin" / "tsc"
    if not tsc.exists():
        raise ErreurExecutionScripts("typescript n'est pas installé avec Playwright sur le serveur.")
    config = {
        "extends": str((depot / "tsconfig.json").resolve()).replace("\\", "/"),
        "compilerOptions": {"noEmit": True, "baseUrl": str(depot.resolve()).replace("\\", "/"),
                            "typeRoots": [str(modules / "@types").replace("\\", "/")], "types": ["node"],
                            "paths": {"@playwright/test": [str(modules / "@playwright" / "test").replace("\\", "/")]}},
        "include": [str(depot.resolve() / d).replace("\\", "/") + "/**/*.ts" for d in (*DOSSIERS_SCRIPTS, *DOSSIERS_GABARIT)]
        + [str(depot.resolve()).replace("\\", "/") + "/playwright.config.ts"],
    }
    tmp = depot.parent / f".tsconfig-verif-{os.getpid()}.json"
    tmp.write_text(json.dumps(config), encoding="utf-8")
    try:
        r = subprocess.run([node, str(tsc), "-p", str(tmp), "--pretty", "false"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, cwd=str(depot))
    finally:
        tmp.unlink(missing_ok=True)
    res = []
    for ligne in (r.stdout or "").splitlines():
        m = RE_TSC.match(ligne.strip())
        if not m:
            continue
        f = Path(m.group(1))
        f = f if f.is_absolute() else (depot / f)
        try:
            rel = f.resolve().relative_to(depot.resolve()).as_posix()
        except ValueError:
            rel = m.group(1)
        res.append({"fichier": rel, "ligne": int(m.group(2)), "code": m.group(4), "message": m.group(6)[:300],
                    "syntaxe": m.group(5).startswith("1")})
    return res


# ---------------------------------------------------------------- contrôle des scripts

def hotes_autorises(url: str, autres_domaines=()) -> list:
    hotes = []
    for lien in [url, *autres_domaines]:
        h = (urlsplit(lien).hostname or "").lower()
        if h and h not in hotes:
            hotes.append(h)
    return hotes


def _module_relatif(depot: Path, fichier: Path, nom: str) -> str:
    """Chemin (relatif au dépôt) du fichier importé, ou '' s'il n'est pas permis."""
    base = (fichier.parent / nom).resolve()
    for c in (base, *(base.with_name(base.name + e) for e in (".js", ".ts", ".json", ".cjs")), base / "index.js", base / "index.ts"):
        if c.is_file():
            try:
                rel = c.relative_to(depot.resolve())
            except ValueError:
                return ""
            sans_ext = rel.with_suffix("").as_posix()
            if rel.parts[0] in DOSSIERS_SCRIPTS or sans_ext in OUTILS_PERMIS:
                return rel.as_posix()
            return ""
    return ""


def controler(depot: Path, hotes: list) -> list:
    """Problèmes qui interdisent l'exécution : [« fichier ligne N : raison »]."""
    problemes = []
    depot = depot.resolve()
    # node_modules dans le dépôt ou au-dessus, jusqu'à la racine de QA Factory (là où l'assistant peut écrire) :
    # Node le chercherait avant celui du serveur.
    racine = RACINE.resolve()
    for parent in [depot, *(p for p in depot.parents if p == racine or racine in p.parents)]:
        if (parent / "node_modules").exists():
            problemes.append(f"{'dossier node_modules' if parent == depot else 'dossier ' + str(parent / 'node_modules')} : "
                             "interdit (il remplacerait Playwright)")
    for p in depot.rglob("*"):
        rel = p.relative_to(depot)
        if p.is_dir() and p.name == "node_modules":
            problemes.append(f"{rel.as_posix()} : dossier node_modules interdit")
        elif p.is_file() and rel.parts[0] in DOSSIERS_SCRIPTS and CONFIGURATIONS_INTERDITES.match(p.name):
            problemes.append(f"{rel.as_posix()} : fichier de configuration interdit dans {rel.parts[0]}/")
    try:
        pj = json.loads((depot / "package.json").read_text(encoding="utf-8"))
        if pj.get("type") not in (None, "commonjs"):
            problemes.append("package.json : « type » modifié (les scripts doivent rester en CommonJS)")
    except (OSError, ValueError):
        problemes.append("package.json illisible")
    for dossier in DOSSIERS_SCRIPTS:
        for f in sorted((depot / dossier).rglob("*")) if (depot / dossier).exists() else []:
            if not f.is_file() or f.suffix.lower() not in EXTENSIONS_CODE:
                continue
            rel = f.relative_to(depot).as_posix()
            try:
                texte = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                problemes.append(f"{rel} : illisible")
                continue
            for n, ligne in enumerate(texte.splitlines(), start=1):
                for motif, raison in INTERDITS:
                    if motif.search(ligne):
                        problemes.append(f"{rel} ligne {n} : {raison}")
                for m in RE_MODULE.finditer(ligne):
                    nom = m.group(2) if m.group(2) is not None else (m.group(4) if m.group(4) is not None else m.group(6))
                    if nom in MODULES_PERMIS:
                        continue
                    if nom.startswith(".") and "$" not in nom and _module_relatif(depot, f, nom):
                        continue
                    problemes.append(f"{rel} ligne {n} : module « {nom[:60]} » non autorisé")
                for m in RE_URL.finditer(ligne):
                    h = m.group(1).lower()
                    if h not in hotes:
                        problemes.append(f"{rel} ligne {n} : adresse hors de l'application ({h})")
    vus, uniques = set(), []
    for p in problemes:
        if p not in vus:
            vus.add(p)
            uniques.append(p)
    return uniques


def retablir_gabarit(depot: Path, langage: str) -> list:
    """Remet les fichiers exécutés du gabarit (configuration, config/, utils/) à l'identique. Renvoie ceux qui ont changé."""
    retablis = []
    for rel, src in auto.fichiers_gabarit(langage).items():
        if rel not in GABARIT_EXECUTE and rel.split("/")[0] not in DOSSIERS_GABARIT:
            continue
        cible = depot / rel
        if not cible.exists() or cible.read_bytes() != src.read_bytes():
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, cible)
            retablis.append(rel)
    for env in depot.glob(".env*"):
        if env.name != ".env.example" and env.is_file():
            env.unlink()
            retablis.append(env.name + " (supprimé)")
    return retablis


# ---------------------------------------------------------------- secrets

def _formes(valeurs) -> list:
    formes = set()
    for v in valeurs or ():
        if isinstance(v, str) and len(v) >= 4:
            formes.add(v)
            formes.add(json.dumps(v, ensure_ascii=False)[1:-1])
            formes.add(json.dumps(v)[1:-1])
    return sorted(formes, key=len, reverse=True)


def nettoyer(texte: str, valeurs) -> str:
    for v in _formes(valeurs):
        texte = texte.replace(v, "<secret retiré>")
    return texte


def _nettoyer_rapport_html(index: Path, valeurs) -> bool:
    """Le rapport HTML range ses données dans un zip en base64 : on retire les secrets de chaque fichier du zip."""
    texte = index.read_text(encoding="utf-8")
    m = RE_DONNEES_RAPPORT.search(texte)
    if not m:
        return False
    src = zipfile.ZipFile(io.BytesIO(base64.b64decode(m.group(2))))
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            contenu = src.read(info)
            try:
                contenu = nettoyer(contenu.decode("utf-8"), valeurs).encode("utf-8")
            except UnicodeDecodeError:
                pass
            z.writestr(info.filename, contenu)
    nouveau = base64.b64encode(sortie.getvalue()).decode("ascii")
    index.write_text(texte[:m.start(2)] + nouveau + texte[m.end(2):], encoding="utf-8")
    return True


def nettoyer_dossier(dossier: Path, valeurs):
    """Retire les secrets de tous les fichiers texte d'une exécution (rapports, sortie, pièces jointes)."""
    if not _formes(valeurs):
        return
    for f in dossier.rglob("*"):
        if not f.is_file() or f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webm", ".zip", ".gif"):
            continue
        if f.name == "index.html" and _nettoyer_rapport_html(f, valeurs):
            continue
        try:
            texte = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        propre = nettoyer(texte, valeurs)
        if propre != texte:
            f.write_text(propre, encoding="utf-8")


# ---------------------------------------------------------------- exécution

def dossier_executions(d: Path) -> Path:
    return auto.dossier_generations(d) / "executions"


def executions(d: Path) -> list:
    base = dossier_executions(d)
    if not base.exists():
        return []
    return sorted((p.name for p in base.iterdir() if (p / "execution.json").exists()), reverse=True)


def dossier_execution(d: Path, ident: str = "") -> Path:
    ident = ident or (executions(d) or [""])[0]
    if not ident or not ident.replace("-", "").isdigit():
        raise ErreurExecutionScripts("Aucune exécution des scripts pour ce projet.")
    e = dossier_executions(d) / ident
    if not (e / "execution.json").exists():
        raise ErreurExecutionScripts(f"Exécution {ident} introuvable.")
    return e


def preparer(projet: str, cas=None, url: str = "", par: str = "") -> Path:
    """Crée le dossier de l'exécution. cas vide : tous les scénarios automatisés."""
    d, _ = charger_projet(projet)
    langage = auto.langage_depot(d)
    if not langage:
        raise ErreurExecutionScripts("Aucun script à exécuter : générez d'abord des scripts.")
    existants = auto.scripts_existants(d)
    if not existants:
        raise ErreurExecutionScripts("Aucun script à exécuter : générez d'abord des scripts.")
    choisis = []
    for x in cas or sorted(existants):
        x = str(x).strip()
        if x and x not in choisis:
            if x not in existants:
                raise ErreurExecutionScripts(f"Aucun script pour le cas {x}.")
            choisis.append(x)
    if not url:
        raise ErreurExecutionScripts("Indiquez d'abord le lien de l'application.")
    try:
        valides = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
        titres = {c["id"]: c.get("titre", "") for c in valides.get("cas_de_tests") or []}
    except (OSError, ValueError):
        titres = {}
    ident = datetime.now().strftime("%Y%m%d-%H%M%S")
    e = dossier_executions(d) / ident
    n = 1
    while e.exists():
        e = dossier_executions(d) / f"{ident[:-2]}{int(ident[-2:]) + n:02d}"
        n += 1
    e.mkdir(parents=True)
    fiche = {"id": e.name, "debut": datetime.now().isoformat(timespec="seconds"), "par": par, "url": url,
             "langage": langage, "langage_libelle": auto.LANGAGES[langage],
             "cas": [{"id": x, "titre": titres.get(x) or re.sub(r"^\[CT\d+\]\s*|\s*(@[\w-]+\s*)+$", "", existants[x]["titre"]),
                      "fichier": existants[x]["fichier"]} for x in choisis]}
    (e / "execution.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return e


def _arreter(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        pass


def environnement(url: str, hotes: list, secrets: dict, modules: Path, e: Path) -> dict:
    """Environnement du processus Playwright : rien de l'application (clés, mots de passe du serveur)."""
    garder = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "TEMP", "TMP", "SystemRoot", "SYSTEMROOT", "windir",
              "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC", "PLAYWRIGHT_BROWSERS_PATH",
              "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "NODE_USE_ENV_PROXY",
              "NODE_EXTRA_CA_CERTS")
    env = {k: os.environ[k] for k in garder if k in os.environ}
    env.update({"CI": "1", "FORCE_COLOR": "0", "BASE_URL": url, "QAF_HOTES_AUTORISES": ";".join(hotes),
                "NODE_PATH": str(modules), "PLAYWRIGHT_JSON_OUTPUT_FILE": str(e / "resultats.json"),
                "PLAYWRIGHT_HTML_OUTPUT_DIR": str(e / "rapport"), "PLAYWRIGHT_HTML_OPEN": "never"})
    for k, v in (secrets or {}).items():
        if re.fullmatch(r"COMPTE_\d+_(IDENTIFIANT|MOT_DE_PASSE)", k):
            env[k] = str(v)
    return env


def progression(e: Path) -> tuple:
    """(tests terminés, total) d'après la sortie du rapporteur « list »."""
    try:
        total = len(json.loads((e / "execution.json").read_text(encoding="utf-8"))["cas"])
    except (OSError, ValueError, KeyError):
        return 0, 0
    faits = set()
    try:
        with (e / "sortie.txt").open(encoding="utf-8", errors="replace") as f:
            for ligne in f:
                m = RE_LIGNE_TEST.match(ligne)
                if m:
                    faits.add(m.group(2))
    except OSError:
        pass
    return min(len(faits), total), total


def _specs(suite, sortie):
    for spec in suite.get("specs") or []:
        sortie.append(spec)
    for s in suite.get("suites") or []:
        _specs(s, sortie)


def _message(erreur) -> str:
    texte = RE_ANSI.sub("", (erreur or {}).get("message") or (erreur or {}).get("value") or "")
    texte = "\n".join(l.rstrip() for l in texte.strip().splitlines() if l.strip())
    return texte[:MAX_MESSAGE]


def _analyser(rapport: dict, demandes: list) -> tuple:
    """(résultats par cas demandé, erreurs générales) à partir du rapport JSON de Playwright."""
    specs = []
    for s in rapport.get("suites") or []:
        _specs(s, specs)
    par_cas = {}
    for spec in specs:
        ct = re.search(r"\[(CT\d{4,})\]", spec.get("title", ""))
        if not ct:
            continue
        for t in spec.get("tests") or []:
            par_cas.setdefault(ct.group(1), []).append((spec, t))
    resultats = []
    for c in demandes:
        trouves = par_cas.get(c["id"]) or []
        if not trouves:
            resultats.append({**c, "statut": "non_execute", "duree_ms": 0, "erreur": "", "essais": 0,
                              "remarque": "Test non lancé (exécution interrompue ou test introuvable)."})
            continue
        spec, t = trouves[0]
        essais = t.get("results") or []
        dernier = essais[-1] if essais else {}
        statut = ETATS_PLAYWRIGHT.get(t.get("status"), "echoue")
        erreurs = dernier.get("errors") or ([dernier["error"]] if dernier.get("error") else [])
        if statut == "instable":
            erreurs = next((r.get("errors") for r in essais if r.get("errors")), []) or []
        remarque = ""
        if statut == "instable":
            remarque = "Échoué au premier essai, réussi au second."
        elif statut == "ignore":
            remarque = next((a.get("description") for a in (t.get("annotations") or []) + (dernier.get("annotations") or [])
                             if a.get("type") == "skip" and a.get("description")), "") or "Test ignoré (test.skip)."
        if len(trouves) > 1:
            remarque = (remarque + " " if remarque else "") + f"{len(trouves)} tests portent la référence {c['id']} : le premier est retenu."
        resultats.append({**c, "statut": statut, "duree_ms": sum(int(r.get("duration") or 0) for r in essais),
                          "erreur": _message(erreurs[0]) if erreurs and statut in ("echoue", "instable") else "",
                          "essais": len(essais), "ligne": f"{spec.get('file', '')}:{spec.get('line', '')}", "remarque": remarque})
    generales = [_message(x) for x in rapport.get("errors") or []]
    return resultats, [g for g in generales if g]


def executer(projet: str, ident: str, url: str, autres_domaines=(), secrets=None, arret=None, duree_max_s: int = 5400) -> dict:
    """Contrôle puis exécute les scripts de l'exécution préparée ; écrit synthese.json et met à jour l'inventaire."""
    d, _ = charger_projet(projet)
    e = dossier_execution(d, ident)
    fiche = json.loads((e / "execution.json").read_text(encoding="utf-8"))
    depot = auto.dossier_depot(d)
    node, cli, modules = playwright()
    hotes = hotes_autorises(url, autres_domaines)
    avertissements = []
    retablis = retablir_gabarit(depot, fiche["langage"])
    if retablis:
        avertissements.append("Fichiers du gabarit rétablis avant l'exécution : " + ", ".join(retablis) + ".")
    problemes = controler(depot, hotes)
    if problemes:
        fiche.update(fin=datetime.now().isoformat(timespec="seconds"), refusee=problemes)
        (e / "execution.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise ErreurExecutionScripts(f"Exécution refusée : {len(problemes)} point(s) interdit(s) dans les scripts. "
                                     + " ; ".join(problemes[:8]) + (" ; …" if len(problemes) > 8 else "")
                                     + " Relancez la génération de ces scripts.")
    typescript = []
    if fiche["langage"] == "ts":
        try:
            typescript = [f"{x['fichier']} ligne {x['ligne']} : {x['message']}" for x in verifier_typescript(depot)][:30]
        except ErreurExecutionScripts as ex:
            avertissements.append(f"TypeScript non vérifié : {ex}")
    motif = r"\[(" + "|".join(re.escape(c["id"]) for c in fiche["cas"]) + r")\]"
    commande = [node, str(cli), "test", "--reporter=list,json,html", f"--output={e / 'test-results'}", "--trace=off",
                "--grep", motif]
    debut = time.time()
    arrete = depasse = False
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with (e / "sortie.txt").open("w", encoding="utf-8", errors="replace") as sortie:
        proc = subprocess.Popen(commande, cwd=str(depot), env=environnement(url, hotes, secrets, modules, e),
                                stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **options)
        while proc.poll() is None:
            if arret and arret():
                arrete = True
                _arreter(proc)
                break
            if time.time() - debut > duree_max_s:
                depasse = True
                _arreter(proc)
                break
            time.sleep(1)
    code = proc.returncode
    shutil.rmtree(e / "test-results", ignore_errors=True)  # pièces jointes déjà copiées dans rapport/data
    nettoyer_dossier(e, (secrets or {}).values())
    try:
        rapport = json.loads((e / "resultats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rapport = {}
    resultats, generales = _analyser(rapport, fiche["cas"])
    if not rapport and not arrete:
        sortie_txt = (e / "sortie.txt").read_text(encoding="utf-8", errors="replace") if (e / "sortie.txt").exists() else ""
        generales.append(RE_ANSI.sub("", sortie_txt).strip()[-MAX_MESSAGE:] or "Playwright s'est arrêté sans résultat.")
    if depasse:
        generales.insert(0, f"Durée maximale dépassée ({duree_max_s // 60} min) : exécution arrêtée.")
    stats = {k: sum(1 for r in resultats if r["statut"] == k) for k in STATUTS}
    stats["total"] = len(resultats)
    fiche.update(fin=datetime.now().isoformat(timespec="seconds"), duree_s=round(time.time() - debut), code_retour=code,
                 arretee=arrete, delai_depasse=depasse)
    (e / "execution.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    synthese = {"execution": fiche, "resultats": resultats, "statistiques": stats, "erreurs": generales,
                "typescript": typescript, "avertissements": avertissements,
                "rapport": (e / "rapport" / "index.html").exists()}
    (e / "synthese.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _reporter_inventaire(d, resultats, fiche)
    journaliser(d, "executer-scripts", f"exécution {fiche['id']} : {stats['reussi']} réussi(s), {stats['echoue']} échoué(s), "
                                       f"{stats['instable']} instable(s), {stats['non_execute']} non exécuté(s)",
                [f"04-livrables/automatisation/executions/{fiche['id']}/synthese.json"])
    return synthese


def _reporter_inventaire(d: Path, resultats: list, fiche: dict):
    f = auto.dossier_generations(d) / "inventaire.json"
    try:
        details = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        details = {}
    for r in resultats:
        if r["statut"] == "non_execute":
            continue
        details.setdefault(r["id"], {})["execution"] = {"statut": r["statut"], "date": fiche["debut"], "id": fiche["id"]}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    auto.ecrire_inventaire(d)


def resume(projet: str) -> dict:
    """Dernière exécution terminée (synthèse) et dernier statut de chaque scénario automatisé."""
    d, _ = charger_projet(projet)
    derniere = None
    for ident in executions(d):
        f = dossier_executions(d) / ident / "synthese.json"
        if f.exists():
            try:
                derniere = json.loads(f.read_text(encoding="utf-8"))
                break
            except ValueError:
                continue
    try:
        details = json.loads((auto.dossier_generations(d) / "inventaire.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        details = {}
    return {"derniere": derniere, "statuts": {ct: (v.get("execution") or {}).get("statut", "") for ct, v in details.items()},
            "historique": [x for x in executions(d) if (dossier_executions(d) / x / "synthese.json").exists()][:10]}


# ---------------------------------------------------------------- archive

def archive(projet: str) -> tuple:
    """(nom, contenu) de l'archive zip du dépôt d'automatisation, sans .env, node_modules ni résultats."""
    d, _ = charger_projet(projet)
    depot = auto.dossier_depot(d)
    langage = auto.langage_depot(d)
    if not langage:
        raise ErreurExecutionScripts("Pas encore de dépôt d'automatisation pour ce projet.")
    racine = f"{projet}-automatisation"
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        noms = set()
        for f in auto.dossier_depot_fichiers(depot):
            rel = f.relative_to(depot).as_posix()
            if f.name.startswith(".env") and f.name != ".env.example":
                continue
            z.write(f, f"{racine}/{rel}")
            noms.add(rel)
        if "README.md" not in noms:
            gabarit = auto.GABARIT / "README.md"
            texte = gabarit.read_text(encoding="utf-8").replace("{{APPLICATION}}", projet) \
                .replace("{{LANGAGE}}", auto.LANGAGES[langage]).replace("{{EXT}}", langage)
            z.writestr(f"{racine}/README.md", texte)
    return f"{racine}-{datetime.now().strftime('%Y%m%d')}.zip", sortie.getvalue()


# ---------------------------------------------------------------- ligne de commande

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)
    a = sp.add_parser("controler")
    a.add_argument("projet")
    a.add_argument("--url", default="")
    a = sp.add_parser("executer")
    a.add_argument("projet")
    a.add_argument("--cas", default="")
    a.add_argument("--url", required=True)
    a.add_argument("--secrets", default="", help="fichier JSON {COMPTE_1_IDENTIFIANT: …}")
    a = sp.add_parser("archive")
    a.add_argument("projet")
    a.add_argument("fichier")
    args = p.parse_args()
    try:
        if args.action == "controler":
            d, fiche = charger_projet(args.projet)
            url = args.url or (fiche.get("application") or {}).get("url") or ""
            problemes = controler(auto.dossier_depot(d), hotes_autorises(url, (fiche.get("application") or {}).get("autres_domaines") or []))
            print("\n".join(problemes) or "Aucun point interdit.")
            sys.exit(1 if problemes else 0)
        elif args.action == "executer":
            secrets = json.loads(Path(args.secrets).read_text(encoding="utf-8")) if args.secrets else {}
            e = preparer(args.projet, [x for x in args.cas.split(",") if x], args.url)
            s = executer(args.projet, e.name, args.url, secrets=secrets)
            print(json.dumps(s["statistiques"], ensure_ascii=False))
        else:
            nom, contenu = archive(args.projet)
            Path(args.fichier).write_bytes(contenu)
            print(f"{args.fichier} ({nom}, {len(contenu)} octets)")
    except (ErreurExecutionScripts, auto.ErreurAutomatisation) as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
