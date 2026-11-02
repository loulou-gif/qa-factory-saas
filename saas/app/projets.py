# -*- coding: utf-8 -*-
"""Opérations sur les dossiers de projets (projets/<code>/), sans IA.

Tout passe par les scripts de outils/ (les mêmes que sur un poste), pour garder une seule
logique entre l'usage en ligne de commande et l'application web.
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import reglages

RE_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
EXTENSIONS_DOCUMENTS = {".pdf", ".docx", ".doc", ".md", ".txt", ".png", ".jpg", ".jpeg", ".xlsx", ".odt"}
VUES_MODIFIABLES = {"cas-de-tests.xlsx", "cas-de-tests.docx"}
IGNORES = {"LISEZMOI.md", ".gitkeep"}


class ErreurProjet(Exception):
    pass


def dossier(code: str) -> Path:
    if not RE_CODE.match(code or ""):
        raise ErreurProjet("Code de projet invalide.")
    d = (reglages.projets / code).resolve()
    if d.parent != reglages.projets.resolve():
        raise ErreurProjet("Code de projet invalide.")
    return d


def existe(code: str) -> bool:
    try:
        return (dossier(code) / "projet.json").exists()
    except ErreurProjet:
        return False


def lister() -> list:
    if not reglages.projets.exists():
        return []
    return sorted(p.name for p in reglages.projets.iterdir() if (p / "projet.json").exists())


def fiche(code: str) -> dict:
    return json.loads((dossier(code) / "projet.json").read_text(encoding="utf-8"))


def ecrire_fiche(code: str, donnees: dict):
    (dossier(code) / "projet.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def script(nom: str, *args, timeout=600) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(reglages.outils / nom), *map(str, args)], cwd=str(reglages.racine),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def contenu(d: Path) -> list:
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.name not in IGNORES and not p.name.startswith("."))


def _resume_analyse(d: Path):
    f = d / "cas-de-tests.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"illisible": True}
    from qa_commun import lire_questions
    qs = lire_questions(d / "ambiguites.md")
    ouvertes = [q for q in qs.values() if q["statut"] == "ouverte"]
    return {
        "version": data.get("meta", {}).get("version"),
        "exigences": len(data.get("exigences") or []),
        "cas": len(data.get("cas_de_tests") or []),
        "questions_ouvertes": len(ouvertes),
        "bloquantes": sorted(qid for qid, q in qs.items() if q["statut"] == "ouverte" and q["gravite"] == "bloquante"),
        "modifie_le": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
    }


def etat(code: str) -> dict:
    d = dossier(code)
    corr = d / "04-livrables" / "squash" / "correspondance.json"
    publie = None
    if corr.exists():
        try:
            c = json.loads(corr.read_text(encoding="utf-8"))
            publie = {"exigences": len(c.get("exigences") or {}), "cas": len(c.get("cas_de_tests") or {}),
                      "le": (c.get("mis_a_jour_le") or "")[:16].replace("T", " ")}
        except json.JSONDecodeError:
            publie = {"illisible": True}
    specs = sorted(p.name for p in (d / "04-livrables" / "specs").glob("*.md")) if (d / "04-livrables" / "specs").exists() else []
    e = {
        "documents": [p.name for p in contenu(d / "01-entrant")],
        "a_valider": _resume_analyse(d / "02-a-valider"),
        "valide": _resume_analyse(d / "03-valide"),
        "publie": publie,
        "specs": specs,
    }
    if not e["documents"]:
        e["etape"] = "documents"
    elif not e["a_valider"] and not e["valide"]:
        e["etape"] = "analyse"
    elif e["a_valider"] and not e["valide"]:
        e["etape"] = "relecture"
    elif e["valide"] and not publie:
        e["etape"] = "publication"
    else:
        e["etape"] = "specs" if not specs else "temps-b"
    return e


def creer(code: str, nom: str, url: str, squash_id, responsable_nom: str):
    if not RE_CODE.match(code):
        raise ErreurProjet("Le code doit faire 2 à 49 caractères : minuscules, chiffres et tirets (ex. orange-efacture).")
    if existe(code):
        raise ErreurProjet(f"Le projet « {code} » existe déjà.")
    args = ["nouveau_projet.py", code, "--libelle", nom or code, "--responsable", responsable_nom or "À renseigner"]
    if url:
        args += ["--url", url]
    if squash_id:
        args += ["--squash-id", str(int(squash_id))]
    r = script(*args)
    if r.returncode:
        raise ErreurProjet((r.stderr or r.stdout).strip() or "Création impossible.")


def nom_sur(nom: str) -> str:
    base = Path(nom or "").name
    base = re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE).strip(" .")
    return base[:120] or "document"


def deposer_document(code: str, nom: str, donnees: bytes) -> str:
    nom = nom_sur(nom)
    if Path(nom).suffix.lower() not in EXTENSIONS_DOCUMENTS:
        raise ErreurProjet(f"Format non accepté. Formats acceptés : {', '.join(sorted(EXTENSIONS_DOCUMENTS))}.")
    if len(donnees) > reglages.taille_max_mo * 1024 * 1024:
        raise ErreurProjet(f"Fichier trop volumineux (plus de {reglages.taille_max_mo} Mo).")
    cible = dossier(code) / "01-entrant" / nom
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_bytes(donnees)
    return nom


def retirer_document(code: str, nom: str):
    e = etat(code)
    if e["a_valider"] or e["valide"]:
        raise ErreurProjet("L'analyse existe déjà : les documents d'entrée ne se retirent plus (ils font foi pour l'analyse).")
    f = dossier(code) / "01-entrant" / nom_sur(nom)
    if f.exists() and f.name not in IGNORES:
        f.unlink()


def fichier_telechargeable(code: str, chemin: str) -> Path:
    """Chemin d'un fichier du projet autorisé au téléchargement (refuse tout ce qui sort du projet)."""
    d = dossier(code)
    f = (d / chemin).resolve()
    if d not in f.parents or not f.is_file() or any(part.startswith(".") for part in f.relative_to(d).parts):
        raise ErreurProjet("Fichier introuvable.")
    if f.relative_to(d).parts[0] not in ("01-entrant", "02-a-valider", "03-valide", "04-livrables"):
        raise ErreurProjet("Fichier introuvable.")
    return f


def televerser_vue(code: str, nom: str, donnees: bytes) -> dict:
    """Remplace l'Excel ou le Word des cas dans 02-a-valider, puis reporte les modifications partout."""
    if nom not in VUES_MODIFIABLES:
        raise ErreurProjet("Seuls cas-de-tests.xlsx et cas-de-tests.docx peuvent être renvoyés. Garder le nom du fichier téléchargé.")
    base = dossier(code) / "02-a-valider"
    if not (base / "cas-de-tests.json").exists():
        raise ErreurProjet("Pas d'analyse en relecture : rien à corriger (les fichiers validés ne se modifient pas).")
    if len(donnees) > reglages.taille_max_mo * 1024 * 1024:
        raise ErreurProjet("Fichier trop volumineux.")
    (base / nom).write_bytes(donnees)
    return synchroniser(code)


def synchroniser(code: str, source: str = "") -> dict:
    args = ["synchroniser_vues.py", code] + (["--source", source] if source else [])
    r = script(*args)
    return {"code": r.returncode, "sortie": (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip(),
            "conflit": r.returncode == 2}


def controle(code: str, dossier_nom: str = "02-a-valider") -> dict:
    r = script("controle.py", code, "--dossier", dossier_nom)
    lignes = r.stdout.splitlines()
    return {"ok": r.returncode == 0, "sortie": r.stdout.strip() + ("\n" + r.stderr.strip() if r.stderr.strip() else ""),
            "erreurs": [l.split("ERREUR : ", 1)[1] for l in lignes if "ERREUR : " in l],
            "avertissements": [l.split("AVERTISSEMENT : ", 1)[1] for l in lignes if "AVERTISSEMENT : " in l]}


def journaliser(code: str, commande: str, resultat: str, fichiers=()):
    from qa_commun import journaliser as j
    j(dossier(code), commande, resultat, list(fichiers))


def valider(code: str, par: str) -> int:
    """Acte de validation du responsable : déplace tout le contenu de 02-a-valider dans 03-valide."""
    d = dossier(code)
    src, dst = d / "02-a-valider", d / "03-valide"
    if not (src / "cas-de-tests.json").exists():
        raise ErreurProjet("Rien à valider : pas d'analyse dans 02-a-valider.")
    if (dst / "cas-de-tests.json").exists():
        raise ErreurProjet("Une version est déjà validée. La remettre d'abord en relecture.")
    c = controle(code)
    if not c["ok"]:
        raise ErreurProjet("Le contrôle signale des erreurs : les corriger avant de valider.\n" + "\n".join(c["erreurs"][:10]))
    dst.mkdir(exist_ok=True)
    n = 0
    for f in sorted(src.iterdir()):
        if f.name in ("LISEZMOI.md",):
            continue
        shutil.move(str(f), str(dst / f.name))
        n += 1
    journaliser(code, "valider", f"validé par {par} (déplacement de 02-a-valider vers 03-valide, {n} fichiers)",
                ["03-valide/cas-de-tests.json"])
    return n


def remettre_en_relecture(code: str, par: str) -> int:
    d = dossier(code)
    src, dst = d / "03-valide", d / "02-a-valider"
    if not (src / "cas-de-tests.json").exists():
        raise ErreurProjet("Aucune version validée.")
    if (dst / "cas-de-tests.json").exists():
        raise ErreurProjet("Une analyse est déjà en relecture dans 02-a-valider.")
    n = 0
    for f in sorted(src.iterdir()):
        if f.name == ".gitkeep":
            continue
        shutil.move(str(f), str(dst / f.name))
        n += 1
    journaliser(code, "remettre-en-relecture", f"par {par} (03-valide vers 02-a-valider, {n} fichiers). "
                "Les éléments déjà publiés dans Squash ne seront pas modifiés par une nouvelle publication.",
                ["02-a-valider/cas-de-tests.json"])
    return n


def lire_journal(code: str) -> list:
    f = dossier(code) / "journal.md"
    if not f.exists():
        return []
    lignes = []
    for l in f.read_text(encoding="utf-8").splitlines():
        cols = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cols) >= 3 and re.match(r"\d{4}-\d{2}-\d{2}", cols[0]):
            lignes.append({"date": cols[0], "commande": cols[1], "resultat": cols[2]})
    return list(reversed(lignes))


def charger_cas(code: str, dossier_nom: str):
    f = dossier(code) / dossier_nom / "cas-de-tests.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# ---------------------------------------------------------------- parcours simplifié

def code_depuis_nom(nom: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", Path(nom).stem).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40].strip("-") or "projet"
    if len(base) < 2:
        base = f"projet-{base}"
    code, n = base, 2
    while existe(code) or (reglages.projets / code).exists():
        code = f"{base}-{n}"
        n += 1
    return code


def nom_depuis_fichier(nom: str) -> str:
    t = re.sub(r"[_\-]+", " ", Path(nom).stem).strip()
    return (t[:1].upper() + t[1:])[:80] or "Projet"


def enregistrer_modifications(code: str, modifications: list) -> int:
    """Applique les modifications faites dans la page de relecture au JSON de 02-a-valider.

    modifications : [{id, titre?, prerequis?, etapes?: [{action, resultat_attendu}]}]
    Renvoie le nombre de cas réellement modifiés (la version augmente de 1 s'il y en a).
    """
    f = dossier(code) / "02-a-valider" / "cas-de-tests.json"
    if not f.exists():
        raise ErreurProjet("Rien à enregistrer : les cas ont déjà été validés.")
    data = json.loads(f.read_text(encoding="utf-8"))
    par_id = {c["id"]: c for c in data.get("cas_de_tests") or []}
    n = 0
    for m in modifications or []:
        c = par_id.get(str(m.get("id", "")))
        if not c:
            raise ErreurProjet(f"Cas {m.get('id')} introuvable.")
        avant = json.dumps(c, sort_keys=True, ensure_ascii=False)
        for champ in ("titre", "prerequis"):
            if champ in m:
                v = str(m[champ] or "").strip()
                if not v:
                    raise ErreurProjet(f"{c['id']} : le champ « {champ} » ne peut pas être vide.")
                c[champ] = v[:2000]
        if "etapes" in m:
            etapes = []
            for e in m["etapes"] or []:
                a, r = str(e.get("action") or "").strip(), str(e.get("resultat_attendu") or "").strip()
                if a or r:
                    if not a or not r:
                        raise ErreurProjet(f"{c['id']} : chaque étape a une action et un résultat attendu.")
                    etapes.append({"action": a[:2000], "resultat_attendu": r[:2000]})
            if not etapes:
                raise ErreurProjet(f"{c['id']} : un cas garde au moins une étape.")
            c["etapes"] = etapes
        if json.dumps(c, sort_keys=True, ensure_ascii=False) != avant:
            n += 1
    if n:
        data.setdefault("meta", {})["version"] = int(data["meta"].get("version") or 0) + 1
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        r = script("rendre_revue.py", code, "--forcer")
        if r.returncode:
            raise ErreurProjet((r.stderr or r.stdout).strip()[-400:])
    return n


def questions(code: str, dossier_nom: str) -> list:
    from qa_commun import _champ, _sections
    f = dossier(code) / dossier_nom / "ambiguites.md"
    if not f.exists():
        return []
    res = []
    for qid, s in _sections(f.read_text(encoding="utf-8"), r"Q-\d{3,}").items():
        champ = lambda n: _champ(s["corps"], n)  # noqa: E731
        res.append({"id": qid, "titre": s["titre"], "type": champ("Type"), "gravite": champ("Gravité").lower(),
                    "source": champ("Source"), "constat": champ("Constat"), "question": champ("Question"),
                    "impact": champ("Impact"), "proposition": champ("Proposition"), "reponse": champ("Réponse"),
                    "statut": champ("Statut").lower()})
    ordre = {"bloquante": 0, "importante": 1, "mineure": 2}
    return sorted(res, key=lambda q: (q["statut"] != "ouverte", ordre.get(q["gravite"], 3), q["id"]))


def jeux(code: str, dossier_nom: str) -> list:
    from qa_commun import _champ, _sections
    f = dossier(code) / dossier_nom / "jeux-de-donnees.md"
    if not f.exists():
        return []
    res = []
    for jid, s in _sections(f.read_text(encoding="utf-8"), r"JDD-\d{3,}").items():
        lignes = []
        for l in s["corps"].splitlines():
            cols = [x.strip() for x in l.strip().strip("|").split("|")]
            if l.strip().startswith("|") and len(cols) >= 2 and not re.match(r"^:?-+:?$", cols[0]) and cols[0].lower() != "champ":
                lignes.append({"champ": cols[0], "valeur": cols[1].strip("`"), "remarque": cols[2] if len(cols) > 2 else ""})
        res.append({"id": jid, "titre": s["titre"], "type": _champ(s["corps"], "Type"), "origine": _champ(s["corps"], "Origine"),
                    "cas": _champ(s["corps"], "Cas concernés"), "sensibilite": _champ(s["corps"], "Sensibilité"),
                    "prerequis": _champ(s["corps"], "Prérequis"), "lignes": lignes})
    return res
