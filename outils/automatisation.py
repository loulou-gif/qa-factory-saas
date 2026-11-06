# -*- coding: utf-8 -*-
"""Automatisation Playwright des cas validés (temps B, lot 3), sans IA.

L'agent écrit les Page Objects et les tests dans le dépôt d'automatisation du projet, en observant
l'application dans le navigateur de la tâche, puis un petit fichier JSON par cas traité
(<generation>/resultats/<CT>.json, format : skill automatisation-playwright). Tout le reste se fait ici :

    python outils/automatisation.py priorites <projet>
    python outils/automatisation.py preparer <projet> --cas CT0001,CT0002 [--langage js|ts] [--url <lien>] [--compte "Rôle"]...
    python outils/automatisation.py consolider <projet> [--generation <AAAAMMJJ-HHMMSS>]

- priorites : classe les cas validés (criticité, usage, stabilité observée aux derniers tests, coût) ;
- preparer : crée ou complète le dépôt projets/<projet>/05-automatisation/ depuis templates/automatisation/
  (JavaScript ou TypeScript, fixé à la création), y copie les specs et écrit la fiche de génération
  04-livrables/automatisation/<id>/generation.json ;
- consolider : retrouve dans le dépôt le test de chaque cas ([CT0001] dans le titre), contrôle la syntaxe
  JavaScript, retire tout secret écrit par erreur, met à jour docs/test-inventory.md et écrit synthese.json.

Les scripts ne sont pas exécutés ici : voir outils/execution_scripts.py.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from qa_commun import RACINE, RE_CT, charger_projet, fonctionnalites, journaliser, lire_questions, slug

DEPOT = "05-automatisation"
GABARIT = RACINE / "templates" / "automatisation"
LANGAGES = {"js": "JavaScript", "ts": "TypeScript"}
CRITICITE = {"CRITICAL": 3, "MAJOR": 2, "MINOR": 1, "UNDEFINED": 1}
LIBELLE_CRITICITE = {"CRITICAL": "critique", "MAJOR": "majeure", "MINOR": "mineure", "UNDEFINED": "non définie"}
IMPORTANCE = {"VERY_HIGH": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
LIBELLE_IMPORTANCE = {"VERY_HIGH": "très haute", "HIGH": "haute", "MEDIUM": "moyenne", "LOW": "basse"}
# Types de test qu'un test fonctionnel Playwright vérifie mal (mesures, ressenti, environnements).
HORS_PLAYWRIGHT = {"performance", "utilisabilite", "compatibilite", "fiabilite", "maintenabilite", "portabilite"}
NIVEAUX = {"prioritaire": "Prioritaires", "utile": "Utiles", "facultatif": "Facultatifs", "deconseille": "Déconseillés"}
STATUTS = {"genere": "Script écrit", "non_genere": "Non généré"}
RE_TITRE_TEST = re.compile(r"""\btest\s*\(\s*(['"`])\s*\[(CT\d{4,})\]\s*(.*?)\1""")
MAX_TEXTE = 1000


class ErreurAutomatisation(Exception):
    pass


def _texte(v, n=MAX_TEXTE) -> str:
    return " ".join(str(v or "").split())[:n] if not isinstance(v, (dict, list)) else ""


def dossier_depot(d: Path) -> Path:
    return d / DEPOT


def dossier_generations(d: Path) -> Path:
    return d / "04-livrables" / "automatisation"


def generations(d: Path) -> list:
    base = dossier_generations(d)
    if not base.exists():
        return []
    return sorted((p.name for p in base.iterdir() if (p / "generation.json").exists()), reverse=True)


def dossier_generation(d: Path, ident: str = "") -> Path:
    ident = ident or (generations(d) or [""])[0]
    if not ident or not ident.replace("-", "").isdigit():
        raise ErreurAutomatisation("Aucune génération de scripts pour ce projet.")
    g = dossier_generations(d) / ident
    if not (g / "generation.json").exists():
        raise ErreurAutomatisation(f"Génération {ident} introuvable.")
    return g


def langage_depot(d: Path) -> str:
    """Langage du dépôt existant ('' s'il n'existe pas encore)."""
    depot = dossier_depot(d)
    if (depot / "playwright.config.ts").exists():
        return "ts"
    if (depot / "playwright.config.js").exists():
        return "js"
    return ""


# ---------------------------------------------------------------- priorités

def _derniers_resultats(d: Path) -> tuple:
    """(statuts {CT: statut} de la dernière campagne consolidée, date, cas dont la correction attend une décision)."""
    base = d / "04-livrables" / "execution"
    if not base.exists():
        return {}, "", set()
    for c in sorted((p for p in base.iterdir() if (p / "synthese.json").exists()), reverse=True):
        try:
            s = json.loads((c / "synthese.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        statuts = {r["id"]: r.get("statut") for r in s.get("resultats") or [] if isinstance(r, dict) and r.get("id")}
        if not any(v in ("reussi", "echoue", "bloque") for v in statuts.values()):
            continue  # campagne arrêtée avant le premier cas : elle ne dit rien de la stabilité
        en_attente = set()
        try:
            mods = json.loads((c / "modifications.json").read_text(encoding="utf-8"))
            if not any(m.get("decision") for m in mods):
                en_attente = {m.get("id") for m in mods}
        except (OSError, ValueError):
            pass
        return statuts, (s.get("campagne") or {}).get("debut", "")[:10], en_attente
    return {}, "", set()


def scripts_existants(d: Path) -> dict:
    """{CT: {fichier, titre}} : tests présents dans le dépôt, repérés par [CT0001] dans le titre."""
    depot = dossier_depot(d)
    res = {}
    if not (depot / "tests").exists():
        return res
    for f in sorted([*(depot / "tests").rglob("*.spec.js"), *(depot / "tests").rglob("*.spec.ts")]):
        try:
            texte = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in RE_TITRE_TEST.finditer(texte):
            res.setdefault(m.group(2), {"fichier": f.relative_to(depot).as_posix(), "titre": f"[{m.group(2)}] {m.group(3).strip()}"})
    return res


def priorites(projet: str) -> dict:
    """Classement des cas validés pour l'automatisation, avec les raisons de chaque note."""
    d, _ = charger_projet(projet)
    f = d / "03-valide" / "cas-de-tests.json"
    if not f.exists():
        raise ErreurAutomatisation("Les cas doivent être validés avant d'être automatisés.")
    data = json.loads(f.read_text(encoding="utf-8"))
    exigences = {e["id"]: e for e in data.get("exigences") or []}
    qs = lire_questions(d / "03-valide" / "ambiguites.md")
    bloquantes = {q for q, v in qs.items() if v["statut"] == "ouverte" and v["gravite"] == "bloquante"}
    statuts, date_tests, a_decider = _derniers_resultats(d)
    existants = scripts_existants(d)
    cas = []
    for c in data.get("cas_de_tests") or []:
        note, raisons, alertes = 0, [], []
        crit = max((exigences.get(x, {}).get("criticite") or "MAJOR" for x in c.get("exigences") or []),
                   key=lambda k: CRITICITE.get(k, 2), default="MAJOR")
        note += CRITICITE.get(crit, 2)
        if CRITICITE.get(crit, 2) >= 3:
            raisons.append("exigence critique")
        imp = c.get("importance") or "MEDIUM"
        note += IMPORTANCE.get(imp, 1)
        if IMPORTANCE.get(imp, 1) >= 2:
            raisons.append(f"importance {LIBELLE_IMPORTANCE.get(imp, imp)}")
        if c.get("type") == "nominal":
            note += 2
            raisons.append("parcours nominal, le plus utilisé")
        else:
            note += 1
        st = statuts.get(c["id"])
        deconseille = ""
        if st == "reussi":
            note += 2
            raisons.append("réussi aux derniers tests : comportement stable")
        elif st == "echoue":
            note -= 1
            alertes.append("échoué aux derniers tests : le script échouera tant que l'anomalie n'est pas corrigée")
        elif st == "bloque":
            deconseille = "bloqué aux derniers tests : à rejouer avant d'automatiser"
        else:
            note += 1  # stabilité inconnue (jamais exécuté) : valeur neutre
            if statuts:
                alertes.append("non exécuté aux derniers tests")
        n = len(c.get("etapes") or [])
        if n <= 4:
            note += 1
            raisons.append(f"court ({n} étape{'s' if n > 1 else ''})")
        elif n > 8:
            note -= 1
            alertes.append(f"long ({n} étapes) : plus coûteux à écrire et à maintenir")
        if c.get("type_test") in HORS_PLAYWRIGHT:
            deconseille = f"test de {c.get('type_test')} : un script fonctionnel Playwright le vérifie mal"
        q = sorted(set(c.get("questions") or []) & bloquantes)
        if q:
            deconseille = f"en attente d'une réponse bloquante ({', '.join(q)})"
        if c["id"] in a_decider:
            note -= 1
            alertes.append("correction du cas proposée par les derniers tests, pas encore décidée")
        niveau = "deconseille" if deconseille else ("prioritaire" if note >= 10 else "utile" if note >= 8 else "facultatif")
        cas.append({"id": c["id"], "titre": c.get("titre", ""), "fonctionnalite": c.get("fonctionnalite", ""),
                    "note": note, "niveau": niveau, "raisons": raisons, "alertes": alertes, "deconseille": deconseille,
                    "criticite": LIBELLE_CRITICITE.get(crit, crit), "etapes": n, "dernier_statut": st or "",
                    "script": existants.get(c["id"]),
                    "coche": niveau == "prioritaire" and c["id"] not in existants})
    ordre = list(NIVEAUX)
    cas.sort(key=lambda x: (ordre.index(x["niveau"]), -x["note"], x["id"]))
    return {"cas": cas, "tests_du": date_tests, "langage": langage_depot(d),
            "resume": {k: sum(1 for x in cas if x["niveau"] == k) for k in NIVEAUX},
            "automatises": len([x for x in cas if x["script"]])}


# ---------------------------------------------------------------- dépôt d'automatisation

def _remplacer(texte: str, valeurs: dict) -> str:
    for k, v in valeurs.items():
        texte = texte.replace("{{" + k + "}}", v)
    return texte


def fichiers_gabarit(langage: str) -> dict:
    """{chemin dans le dépôt: fichier du gabarit} ; en TypeScript, les fichiers de ts/ remplacent leurs équivalents JS."""
    res = {}
    for src in GABARIT.rglob("*"):
        rel = src.relative_to(GABARIT)
        if src.is_dir() or rel.parts[0] == "ts":
            continue
        if langage == "ts" and src.suffix == ".js" and (GABARIT / "ts" / rel.with_suffix(".ts")).exists():
            continue
        res[rel.as_posix()] = src
    if langage == "ts":
        for src in (GABARIT / "ts").rglob("*"):
            if src.is_file():
                res[src.relative_to(GABARIT / "ts").as_posix()] = src
    return res


def initialiser_depot(projet: str, langage: str, fiche: dict, data: dict, url: str, actions: str) -> Path:
    """Crée le dépôt depuis templates/automatisation/."""
    d, _ = charger_projet(projet)
    depot = dossier_depot(d)
    gabarit = fichiers_gabarit(langage)
    if depot.exists() and langage_depot(d):
        # Dépôt existant : seules les règles de l'agent (fichier du gabarit, pas du testeur) suivent le gabarit à jour.
        a_completer = ("agents/AGENTS.md",)
        shutil.copy2(gabarit["agents/AGENTS.md"], depot / "agents" / "AGENTS.md")
    else:
        a_completer = ("package.json", "README.md", "agents/AGENTS.md", "agents/project-overview.md")
        depot.mkdir(parents=True, exist_ok=True)
        for rel, src in gabarit.items():
            cible = depot / rel
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, cible)
    from execution import ACTIONS
    valeurs = {"CODE": projet, "APPLICATION": fiche.get("libelle") or fiche.get("nom") or projet, "URL": url or "à renseigner",
               "ESPACES": ", ".join(fonctionnalites(data)) or "à renseigner", "ACTIONS_AUTORISEES": ACTIONS.get(actions, actions),
               "LANGAGE": LANGAGES[langage], "EXT": langage, "CLIENT": str(fiche.get("client") or "à renseigner"),
               "ENVIRONNEMENT": str((fiche.get("application") or {}).get("environnement") or "à confirmer")}
    for nom in a_completer:
        f = depot / nom
        if f.exists():
            texte = re.sub(r"Remplacer les marqueurs `\{\{…\}\}` par les valeurs de `projet.json` ; ",
                           "Complété par QA Factory avec les valeurs du projet ; ", f.read_text(encoding="utf-8"))
            f.write_text(_remplacer(texte, valeurs), encoding="utf-8")
    (depot / "docs").mkdir(exist_ok=True)
    return depot


def _env_exemple(depot: Path, comptes, url: str):
    lignes = ["# Copier en .env (jamais versionné) et renseigner les valeurs.",
              "# URL de l'application (environnement de test autorisé)", f"BASE_URL={url}", ""]
    for i, lib in enumerate(comptes or ["Compte de test"], start=1):
        lignes += [f"# Compte {i} : {lib} (compte de test dédié, jamais un compte personnel)",
                   f"COMPTE_{i}_IDENTIFIANT=", f"COMPTE_{i}_MOT_DE_PASSE=", ""]
    (depot / ".env.example").write_text("\n".join(lignes), encoding="utf-8")


def preparer(projet: str, cas, langage: str = "js", url: str = "", comptes=(), actions: str = "lecture-seule",
             modele: str = "", par: str = "", navigateur: str = "") -> Path:
    d, fiche = charger_projet(projet)
    f = d / "03-valide" / "cas-de-tests.json"
    if not f.exists():
        raise ErreurAutomatisation("Les cas doivent être validés avant d'être automatisés.")
    data = json.loads(f.read_text(encoding="utf-8"))
    if langage not in LANGAGES:
        raise ErreurAutomatisation("Langage inconnu : JavaScript ou TypeScript.")
    existant = langage_depot(d)
    if existant and existant != langage:
        raise ErreurAutomatisation(f"Le dépôt d'automatisation est déjà en {LANGAGES[existant]} : "
                                   "un dépôt garde un seul langage.")
    tous = {c["id"]: c for c in data.get("cas_de_tests") or []}
    choisis = []
    for x in cas:
        x = str(x).strip()
        if x and x not in choisis:
            if x not in tous:
                raise ErreurAutomatisation(f"Cas {x} inconnu dans la version validée.")
            choisis.append(x)
    if not choisis:
        raise ErreurAutomatisation("Cochez au moins un scénario à automatiser.")
    if len(choisis) > 60:
        raise ErreurAutomatisation("60 scénarios au plus par génération.")
    depot = initialiser_depot(projet, langage, fiche, data, url, actions)
    _env_exemple(depot, comptes, url)
    specs = d / "04-livrables" / "specs"
    features = depot / "agents" / "features"
    features.mkdir(parents=True, exist_ok=True)
    for s in specs.glob("*.md") if specs.exists() else []:
        shutil.copy2(s, features / s.name)
    ident = datetime.now().strftime("%Y%m%d-%H%M%S")
    g = dossier_generations(d) / ident
    n = 1
    while g.exists():
        g = dossier_generations(d) / f"{ident[:-2]}{int(ident[-2:]) + n:02d}"
        n += 1
    (g / "resultats").mkdir(parents=True)
    existants = scripts_existants(d)
    generation = {
        "id": g.name, "debut": datetime.now().isoformat(timespec="seconds"), "url": url, "actions": actions,
        "langage": langage, "langage_libelle": LANGAGES[langage], "modele": modele, "par": par, "navigateur": navigateur,
        "depot": depot.relative_to(RACINE).as_posix() if RACINE in depot.parents else str(depot),
        "version_cas": (data.get("meta") or {}).get("version"),
        "comptes": [{"numero": i, "libelle": str(lib)[:80],
                     "secret_identifiant": f"COMPTE_{i}_IDENTIFIANT", "secret_mot_de_passe": f"COMPTE_{i}_MOT_DE_PASSE"}
                    for i, lib in enumerate(comptes, start=1)],
        "cas": [{"id": x, "titre": tous[x].get("titre", ""), "fonctionnalite": tous[x].get("fonctionnalite", ""),
                 "spec": f"agents/features/{slug(tous[x].get('fonctionnalite') or 'divers')}.md",
                 "test": f"tests/{slug(tous[x].get('fonctionnalite') or 'divers')}/{slug(tous[x].get('fonctionnalite') or 'divers')}.spec.{langage}",
                 "existant": (existants.get(x) or {}).get("fichier", "")} for x in choisis],
    }
    (g / "generation.json").write_text(json.dumps(generation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fiche.setdefault("automatisation", {}).update(depot=DEPOT, langage=langage)
    fiche["automatisation"].pop("note", None)
    (d / "projet.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return g


# ---------------------------------------------------------------- consolidation

def _verifier_syntaxe(depot: Path, fichiers: list, avertissements: list) -> dict:
    """{fichier: erreur} : `node --check` pour le JavaScript, lecture pour le JSON (TypeScript : _verifier_typescript)."""
    erreurs = {}
    node = shutil.which("node")
    for rel in fichiers:
        f = depot / rel
        if f.suffix == ".json":
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                erreurs[rel] = f"JSON invalide : {e}"
        elif f.suffix == ".js" and node:
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=60)
            if r.returncode:
                lignes = [l for l in (r.stderr or "").splitlines() if l.strip()]
                erreurs[rel] = next((l for l in lignes if "Error" in l), lignes[-1] if lignes else "erreur de syntaxe")[:300]
    if not node and any(x.endswith(".js") for x in fichiers):
        avertissements.append("Node.js absent : syntaxe JavaScript non vérifiée.")
    return erreurs


def _verifier_typescript(depot: Path, fichiers: list, avertissements: list) -> dict:
    """{fichier: erreur de syntaxe} relevées par tsc ; les erreurs de type sont des avertissements (Playwright exécute quand même)."""
    import execution_scripts
    try:
        diagnostics = execution_scripts.verifier_typescript(depot)
    except execution_scripts.ErreurExecutionScripts as e:
        avertissements.append(f"TypeScript non vérifié : {e}")
        return {}
    erreurs = {}
    for x in diagnostics:
        if x["fichier"] not in fichiers:
            continue
        if x["syntaxe"]:
            erreurs.setdefault(x["fichier"], f"ligne {x['ligne']} : {x['message']}")
        else:
            avertissements.append(f"{x['fichier']} ligne {x['ligne']} : {x['message']} (TypeScript)")
    return erreurs


def _retirer_secrets(depot: Path, valeurs, avertissements: list) -> int:
    """Remplace toute valeur secrète écrite dans le dépôt (l'agent ne les voit pas, mais on vérifie)."""
    valeurs = sorted({v for v in valeurs or () if isinstance(v, str) and len(v) >= 4}, key=len, reverse=True)
    if not valeurs:
        return 0
    n = 0
    for f in dossier_depot_fichiers(depot):
        try:
            texte = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        nouveau = texte
        for v in valeurs:
            nouveau = nouveau.replace(v, "<secret retiré>")
        if nouveau != texte:
            f.write_text(nouveau, encoding="utf-8")
            n += 1
            avertissements.append(f"{f.relative_to(depot).as_posix()} : un secret y était écrit, il a été retiré.")
    return n


def dossier_depot_fichiers(depot: Path) -> list:
    ignores = {"node_modules", "test-results", "playwright-report", "allure-results", "allure-report", "evidence", "blob-report"}
    return sorted(f for f in depot.rglob("*") if f.is_file() and not ignores & set(f.relative_to(depot).parts)
                  and f.name != ".env")


STATUTS_INVENTAIRE = {"reussi": "PASSED", "echoue": "FAILED", "instable": "FLAKY", "ignore": "SKIPPED"}


def ecrire_inventaire(d: Path):
    """docs/test-inventory.md : chaque test du dépôt, son cas et le dernier résultat de son exécution depuis l'application."""
    depot = dossier_depot(d)
    try:
        data = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    try:
        details = json.loads((dossier_generations(d) / "inventaire.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        details = {}
    titres = {c["id"]: c for c in data.get("cas_de_tests") or []}
    existants = scripts_existants(d)
    lignes = ["# Inventaire des tests automatisés", "",
              f"Mis à jour par QA Factory le {datetime.now().strftime('%d/%m/%Y %H:%M')}. Statut : dernier résultat de "
              "l'exécution depuis l'application (NOT_RUN : pas encore exécuté depuis sa dernière écriture).", "",
              "| ID | Scénario | Test | Fichier | Statut | Exécuté le | Locators vérifiés | Commentaire |",
              "|---|---|---|---|---|---|---|---|"]
    for ct in sorted(existants):
        dt = details.get(ct) or {}
        ex = dt.get("execution") or {}
        verif = {True: "oui", False: "non"}.get(dt.get("locators_verifies"), "—")
        com = (dt.get("remarque") or "").replace("|", "/")
        lignes.append(f"| {ct} | {(titres.get(ct) or {}).get('titre', '').replace('|', '/')} | {existants[ct]['titre'].replace('|', '/')} "
                      f"| `{existants[ct]['fichier']}` | {STATUTS_INVENTAIRE.get(ex.get('statut'), 'NOT_RUN')} "
                      f"| {(ex.get('date') or '—')[:16].replace('T', ' ')} | {verif} | {com} |")
    (depot / "docs").mkdir(parents=True, exist_ok=True)
    (depot / "docs" / "test-inventory.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")


def consolider(projet: str, ident: str = "", secrets=()) -> dict:
    d, _ = charger_projet(projet)
    g = dossier_generation(d, ident)
    gen = json.loads((g / "generation.json").read_text(encoding="utf-8"))
    depot = dossier_depot(d)
    if not depot.exists():
        raise ErreurAutomatisation("Dépôt d'automatisation introuvable.")
    avertissements = []
    _retirer_secrets(depot, secrets, avertissements)
    debut = datetime.fromisoformat(gen["debut"]).timestamp() - 1
    ecrits = [f.relative_to(depot).as_posix() for f in dossier_depot_fichiers(depot)
              if f.stat().st_mtime >= debut and f.relative_to(depot).parts[0] in ("pages", "tests", "data", "utils")]
    erreurs = _verifier_syntaxe(depot, ecrits, avertissements)
    if gen["langage"] == "ts":
        erreurs.update(_verifier_typescript(depot, ecrits, avertissements))
    existants = scripts_existants(d)
    demandes = {c["id"]: c for c in gen["cas"]}
    # Ce que l'agent dit de chaque cas (locators vérifiés, remarque) ; la présence du test est vérifiée dans le dépôt.
    details = {}
    precedent = g.parent / "inventaire.json"
    try:
        details = json.loads(precedent.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        details = {}
    resultats = []
    for ct in demandes:
        r = {}
        fr = g / "resultats" / f"{ct}.json"
        if fr.exists():
            try:
                r = json.loads(fr.read_text(encoding="utf-8"))
                r = r if isinstance(r, dict) else {}
            except (ValueError, UnicodeDecodeError):
                avertissements.append(f"{fr.name} : JSON illisible, ignoré.")
        script = existants.get(ct)
        erreur = erreurs.get(script["fichier"]) if script else ""
        statut = "genere" if script and not erreur else "non_genere"
        remarque = _texte(r.get("remarque"))
        if not script:
            remarque = remarque or "Aucun test [" + ct + "] trouvé dans le dépôt."
        elif erreur:
            remarque = f"Erreur de syntaxe dans {script['fichier']} : {erreur}"
        verifies = r.get("locators_verifies") if isinstance(r.get("locators_verifies"), bool) else None
        resultats.append({"id": ct, "titre": demandes[ct]["titre"], "fonctionnalite": demandes[ct]["fonctionnalite"],
                          "statut": statut, "fichier": (script or {}).get("fichier", ""), "test": (script or {}).get("titre", ""),
                          "locators_verifies": verifies, "remarque": remarque,
                          "nouveau": not demandes[ct].get("existant")})
        if script:
            # Script réécrit : le résultat de sa dernière exécution ne vaut plus pour lui.
            details[ct] = {"locators_verifies": verifies, "remarque": "" if statut == "genere" and not r.get("remarque") else remarque,
                           "generation": gen["id"]}
    precedent.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for rel, e in erreurs.items():
        if not any(x["fichier"] == rel for x in resultats):
            avertissements.append(f"{rel} : {e}")
    ecrire_inventaire(d)
    synthese = {
        "generation": {**gen, "fin": datetime.now().isoformat(timespec="seconds")},
        "resultats": resultats,
        "statistiques": {"demandes": len(resultats), "generes": sum(1 for x in resultats if x["statut"] == "genere"),
                         "non_generes": sum(1 for x in resultats if x["statut"] == "non_genere"),
                         "locators_verifies": sum(1 for x in resultats if x["locators_verifies"] is True),
                         "automatises": len(existants)},
        "fichiers": sorted(ecrits),
        "avertissements": avertissements,
    }
    (g / "synthese.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = synthese["statistiques"]
    journaliser(d, "automatiser", f"génération {gen['id']} ({gen['langage_libelle']}) : {s['generes']} script(s) écrit(s), "
                                  f"{s['non_generes']} non généré(s)", [f"{DEPOT}/docs/test-inventory.md"])
    return synthese


def resume(projet: str) -> dict:
    """Dernière génération consolidée et nombre de scénarios automatisés, pour la page du projet."""
    d, fiche = charger_projet(projet)
    dernier = None
    for ident in generations(d):
        f = dossier_generations(d) / ident / "synthese.json"
        if f.exists():
            try:
                dernier = json.loads(f.read_text(encoding="utf-8"))
                break
            except ValueError:
                continue
    return {"langage": langage_depot(d), "automatises": len(scripts_existants(d)), "derniere": dernier}


# ---------------------------------------------------------------- ligne de commande

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)
    a = sp.add_parser("priorites")
    a.add_argument("projet")
    a = sp.add_parser("preparer")
    a.add_argument("projet")
    a.add_argument("--cas", required=True)
    a.add_argument("--langage", default="js", choices=list(LANGAGES))
    a.add_argument("--url", default="")
    a.add_argument("--compte", action="append", default=[])
    a.add_argument("--actions", default="lecture-seule")
    a = sp.add_parser("consolider")
    a.add_argument("projet")
    a.add_argument("--generation", default="")
    args = p.parse_args()
    try:
        if args.action == "priorites":
            r = priorites(args.projet)
            for c in r["cas"]:
                print(f"{c['id']}  {NIVEAUX[c['niveau']][:-1]:<12} note {c['note']:>2}  {c['titre']}"
                      + (f"  [{c['deconseille']}]" if c["deconseille"] else ""))
        elif args.action == "preparer":
            g = preparer(args.projet, args.cas.split(","), args.langage, args.url, args.compte, args.actions)
            print(f"Génération préparée : {g}")
        else:
            s = consolider(args.projet, args.generation)
            print(json.dumps(s["statistiques"], ensure_ascii=False))
    except ErreurAutomatisation as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
