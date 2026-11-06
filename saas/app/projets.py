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


MOTS_MINIMUM = 150  # en dessous, un document ne permet pas de concevoir des cas de tests


def lire_texte(nom: str, donnees: bytes) -> tuple:
    """(texte, remarque) d'un document déposé. remarque explique pourquoi aucun texte n'a pu être lu."""
    import io
    ext = Path(nom).suffix.lower()
    try:
        if ext in (".md", ".txt"):
            return donnees.decode("utf-8", errors="replace"), ""
        if ext == ".pdf":
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(donnees))
            if pdf.is_encrypted:
                return "", "PDF protégé par un mot de passe"
            texte = "\n".join((page.extract_text() or "") for page in pdf.pages)
            return texte, "" if texte.strip() else "PDF scanné (image) : aucun texte lisible"
        if ext == ".docx":
            import docx
            d = docx.Document(io.BytesIO(donnees))
            lignes = [para.text for para in d.paragraphs]
            for t in d.tables:
                for ligne in t.rows:
                    lignes.append(" | ".join(c.text for c in ligne.cells))
            return "\n".join(lignes), ""
        if ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(donnees), read_only=True, data_only=True)
            lignes = []
            for ws in wb.worksheets:
                lignes.append(f"## {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    valeurs = [str(v) for v in row if v not in (None, "")]
                    if valeurs:
                        lignes.append(" | ".join(valeurs))
            return "\n".join(lignes), ""
        if ext == ".odt":
            import zipfile
            xml = zipfile.ZipFile(io.BytesIO(donnees)).read("content.xml").decode("utf-8", errors="replace")
            xml = re.sub(r"</text:(p|h)>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml), ""
        if ext == ".doc":
            return "", "ancien format Word (.doc) : l'enregistrer en .docx ou en PDF"
        if ext in (".png", ".jpg", ".jpeg"):
            return "", "image (maquette)"
    except Exception:  # noqa: BLE001
        return "", "fichier illisible ou endommagé"
    return "", "format non lu"


def evaluer_documents(documents: list) -> tuple:
    """documents = [(nom, octets)]. Renvoie (textes {nom: texte}, None) si le contenu suffit,
    sinon (textes, message) expliquant pourquoi l'analyse ne peut pas produire de cas de tests."""
    textes, remarques, mots = {}, [], 0
    for nom, donnees in documents:
        texte, remarque = lire_texte(nom, donnees)
        n = len(re.findall(r"\w{2,}", texte))
        mots += n
        if texte.strip():
            textes[nom] = texte
        if remarque and remarque != "image (maquette)":
            remarques.append(f"{nom} : {remarque}")
        elif not remarque and n < MOTS_MINIMUM:
            remarques.append(f"{nom} : {n} mot{'s' if n > 1 else ''} seulement")
    if mots >= MOTS_MINIMUM:
        return textes, None
    if all(Path(nom).suffix.lower() in (".png", ".jpg", ".jpeg") for nom, _ in documents):
        message = ("Les maquettes seules ne suffisent pas pour concevoir des cas de tests : "
                   "déposez-les avec le cahier des charges (ou les User Stories) qui décrit les règles de gestion.")
    else:
        message = ("Pas assez de contenu exploitable pour générer des cas de tests"
                   + (" (" + " ; ".join(remarques) + ")" if remarques else "")
                   + ". Déposez un cahier des charges, des User Stories ou des spécifications qui décrivent "
                     "les fonctionnalités et les règles de gestion.")
    return textes, message


def enregistrer_textes(code: str, textes: dict):
    """Copie texte des documents dans 01-entrant/_texte/ : l'assistant les lit directement,
    sans conversion (utile sous Windows et avec les modèles légers)."""
    d = dossier(code) / "01-entrant" / "_texte"
    d.mkdir(parents=True, exist_ok=True)
    for nom, texte in textes.items():
        (d / (nom_sur(nom) + ".txt")).write_text(texte, encoding="utf-8")


def supprimer_projet_vide(code: str):
    """Retire un projet créé à l'instant et jamais analysé (dépôt refusé)."""
    import shutil
    d = dossier(code)
    if d.exists() and not etat(code)["a_valider"] and not etat(code)["valide"]:
        shutil.rmtree(d, ignore_errors=True)


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
                lignes.append({"champ": cols[0], "valeur": cols[1].replace("`", "").strip(), "remarque": cols[2] if len(cols) > 2 else ""})
        res.append({"id": jid, "titre": s["titre"], "type": _champ(s["corps"], "Type"), "origine": _champ(s["corps"], "Origine"),
                    "cas": _champ(s["corps"], "Cas concernés"), "sensibilite": _champ(s["corps"], "Sensibilité"),
                    "prerequis": _champ(s["corps"], "Prérequis"), "lignes": lignes})
    return res


# ---------------------------------------------------------------- questions : réponses

def _section_md(texte: str, ident: str) -> tuple:
    """(début, fin) de la section '### <ident> — …' dans un fichier Markdown."""
    m = re.search(rf"^###\s+{re.escape(ident)}\b.*$", texte, flags=re.M)
    if not m:
        raise ErreurProjet(f"{ident} introuvable.")
    suite = re.search(r"^#{1,3}\s", texte[m.end():], flags=re.M)
    return m.start(), (m.end() + suite.start()) if suite else len(texte)


def _remplacer_champ(section: str, nom: str, valeur: str) -> str:
    ligne = f"- **{nom}** : {valeur}".rstrip()
    motif = rf"^[ \t]*-[ \t]*\*\*{nom}\*\*[ \t]*:.*$"
    if re.search(motif, section, flags=re.M | re.I):
        return re.sub(motif, lambda _: ligne, section, count=1, flags=re.M | re.I)
    return section.rstrip("\n") + "\n" + ligne + "\n\n"


def repondre_question(code: str, qid: str, reponse: str, faux_positif: bool, auteur: str) -> str:
    """Enregistre la réponse à une question (ou la classe en faux positif) dans ambiguites.md.
    Une question répondue ou close ne bloque plus les cas qui en dépendaient."""
    if not re.fullmatch(r"Q-\d{3,}", qid or ""):
        raise ErreurProjet("Question inconnue.")
    reponse = " ".join((reponse or "").split())
    if not faux_positif and not reponse:
        raise ErreurProjet("Écrivez la réponse, ou indiquez que la question est sans objet.")
    e = etat(code)
    nom_dossier = "02-a-valider" if e["a_valider"] else "03-valide"
    f = dossier(code) / nom_dossier / "ambiguites.md"
    if not f.exists():
        raise ErreurProjet("Pas de questions pour ce projet.")
    texte = f.read_text(encoding="utf-8")
    debut, fin = _section_md(texte, qid)
    from datetime import date
    signature = f"({auteur}, {date.today():%d/%m/%Y})"
    if faux_positif:
        valeur, statut = f"Sans objet : faux positif{(' — ' + reponse) if reponse else ''} {signature}", "close"
    else:
        valeur, statut = f"{reponse} {signature}", "répondue"
    section = _remplacer_champ(_remplacer_champ(texte[debut:fin], "Réponse", valeur), "Statut", statut)
    f.write_text(texte[:debut] + section + texte[fin:], encoding="utf-8")
    journaliser(code, "réponse", f"{qid} : {statut} par {auteur}", [f"{nom_dossier}/ambiguites.md"])
    return statut


def cas_bloques(code: str, nom_dossier: str) -> dict:
    """{CT…: [Q…]} : cas suspendus à une question bloquante encore ouverte."""
    data = charger_cas(code, nom_dossier) or {}
    ouvertes = {q["id"] for q in questions(code, nom_dossier) if q["statut"] == "ouverte" and q["gravite"] == "bloquante"}
    res = {}
    for c in data.get("cas_de_tests", []):
        qs = sorted(set(c.get("questions") or []) & ouvertes)
        if qs:
            res[c["id"]] = qs
    return res


# ---------------------------------------------------------------- jeux de données : modification

def enregistrer_jeux(code: str, modifications: list, auteur: str) -> int:
    """modifications = [{id: JDD-…, lignes: [{champ, valeur, remarque}]}] : réécrit le tableau de chaque jeu."""
    e = etat(code)
    nom_dossier = "02-a-valider" if e["a_valider"] else "03-valide"
    f = dossier(code) / nom_dossier / "jeux-de-donnees.md"
    if not f.exists():
        raise ErreurProjet("Pas de jeux de données pour ce projet.")
    texte = f.read_text(encoding="utf-8")
    nettoyer = lambda v: " ".join(str(v or "").replace("|", "/").split())  # noqa: E731
    n = 0
    for m in modifications or []:
        jid = m.get("id") or ""
        if not re.fullmatch(r"JDD-\d{3,}", jid):
            raise ErreurProjet("Jeu de données inconnu.")
        lignes = [{k: nettoyer(l.get(k)) for k in ("champ", "valeur", "remarque")} for l in m.get("lignes") or []]
        lignes = [l for l in lignes if l["champ"]]
        if not lignes:
            raise ErreurProjet(f"{jid} : au moins un champ est nécessaire.")
        if len({l["champ"].lower() for l in lignes}) != len(lignes):
            raise ErreurProjet(f"{jid} : deux champs portent le même nom.")
        debut, fin = _section_md(texte, jid)
        section = texte[debut:fin]
        tableau = "| Champ | Valeur | Remarque |\n|---|---|---|\n" + "".join(
            f"| {l['champ']} | {('`' + l['valeur'] + '`') if l['valeur'] and not l['valeur'].startswith('variable ') else l['valeur']} | {l['remarque']} |\n"
            for l in lignes)
        bloc = re.search(r"(^\|.*\|\s*\n?)+", section, flags=re.M)
        if bloc:
            section = section[:bloc.start()] + tableau + section[bloc.end():]
        else:
            section = section.rstrip("\n") + "\n\n" + tableau
        if not section.endswith("\n\n"):
            section = section.rstrip("\n") + "\n\n"
        texte = texte[:debut] + section + texte[fin:]
        n += 1
    f.write_text(texte.rstrip("\n") + "\n", encoding="utf-8")
    journaliser(code, "jeux de données", f"{n} jeu(x) modifié(s) par {auteur}", [f"{nom_dossier}/jeux-de-donnees.md"])
    return n


# ---------------------------------------------------------------- publication Squash : préparation

def nom_parametre(champ: str) -> str:
    """Nom de paramètre accepté par Squash (lettres, chiffres, _ et -)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", champ).encode("ascii", "ignore").decode("ascii")
    return (re.sub(r"[^A-Za-z0-9_-]+", "_", t).strip("_") or "parametre")[:255]


def preparer_publication(code: str) -> dict:
    """Fichier réellement envoyé à Squash, tiré de 03-valide :
    - sans les cas suspendus à une question bloquante ouverte (ils partiront quand elle sera répondue) ;
    - chaque jeu de données porte son nom complet et ses paramètres ; le prérequis du cas les cite
      (${paramètre}), pour que Squash affiche les valeurs du jeu choisi à l'exécution.
    Les jeux et leurs valeurs vont dans jeux-squash.json, que le module Squash utilise pour les renseigner."""
    from qa_commun import empreinte  # noqa: F401  (même module que l'empreinte de publication)
    d = dossier(code)
    data = charger_cas(code, "03-valide")
    if not data:
        raise ErreurProjet("Rien de validé à publier (03-valide est vide).")
    bloques = cas_bloques(code, "03-valide")
    jeux_liste = {j["id"]: j for j in jeux(code, "03-valide")}
    noms = {jid: f"{jid} {j['titre']}"[:255] for jid, j in jeux_liste.items()}
    publies, jeux_squash = [], []
    for c in data["cas_de_tests"]:
        if c["id"] in bloques:
            continue
        c = dict(c)
        refs = [r for r in (c.get("jeux_de_donnees") or []) if r in jeux_liste]
        if refs:
            params = []
            for r in refs:
                for l in jeux_liste[r]["lignes"]:
                    p = nom_parametre(l["champ"])
                    if p not in [x[0] for x in params]:
                        params.append((p, l["champ"]))
            mention = "Données (jeu choisi à l'exécution) : " + ", ".join(f"{champ} = ${{{p}}}" for p, champ in params)
            c["prerequis"] = ((c.get("prerequis") or "").rstrip() + "\n" + mention).strip()
            c["jeux_de_donnees"] = [noms[r] for r in refs]
            for r in refs:
                jeux_squash.append({"cas": c["id"], "nom": noms[r],
                                    "parametres": [{"nom": nom_parametre(l["champ"]), "valeur": l["valeur"]} for l in jeux_liste[r]["lignes"]]})
        else:
            c.pop("jeux_de_donnees", None)
        publies.append(c)
    sortie = dict(data, cas_de_tests=publies)
    dossier_squash = d / "04-livrables" / "squash"
    dossier_squash.mkdir(parents=True, exist_ok=True)
    fpub, fjeux = dossier_squash / "publication.json", dossier_squash / "jeux-squash.json"
    fpub.write_text(json.dumps(sortie, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fjeux.write_text(json.dumps(jeux_squash, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"fichier": fpub, "jeux": fjeux, "exclus": bloques, "nb_cas": len(publies), "nb_jeux": len(jeux_squash)}


# ---------------------------------------------------------------- suivi de ce qui a été envoyé dans Squash

def _empreinte_element(x: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _fichier_envoye(code: str) -> Path:
    return dossier(code) / "04-livrables" / "squash" / "envoye.json"


def empreintes_validees(code: str) -> dict:
    """Empreinte de chaque cas et exigence de 03-valide (contenu tel que validé)."""
    data = charger_cas(code, "03-valide") or {}
    return {"cas_de_tests": {c["id"]: _empreinte_element(c) for c in data.get("cas_de_tests", [])},
            "exigences": {e["id"]: _empreinte_element(e) for e in data.get("exigences", [])}}


def enregistrer_envoi(code: str, non_envoyes=()) -> None:
    """Après un envoi : la version de chaque élément maintenant à jour dans Squash. Les éléments non
    envoyés (échec de mise à jour) gardent leur ancienne empreinte : ils restent à mettre à jour."""
    f = _fichier_envoye(code)
    try:
        ancien = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ancien = {}
    nouveau = empreintes_validees(code)
    try:
        corr = json.loads((dossier(code) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        corr = {}
    sortie = {}
    for genre in ("cas_de_tests", "exigences"):
        dans_squash = set((corr.get(genre) or {}).keys())
        anciens = ancien.get(genre) or {}
        sortie[genre] = {i: (anciens[i] if i in non_envoyes and i in anciens else h)
                         for i, h in nouveau[genre].items() if i in dans_squash and (i not in non_envoyes or i in anciens)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(sortie, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def a_mettre_a_jour(code: str):
    """Cas et exigences déjà dans Squash, modifiés dans QA Factory depuis le dernier envoi.
    None si on ne le sait pas (envoi fait avant ce suivi) : seule une vérification de Squash le dira."""
    f = _fichier_envoye(code)
    if not f.exists():
        return None
    try:
        envoye = json.loads(f.read_text(encoding="utf-8"))
        corr = json.loads((dossier(code) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    actuel = empreintes_validees(code)
    bloques = cas_bloques(code, "03-valide")
    ids = []
    for genre in ("exigences", "cas_de_tests"):
        for i, h in actuel[genre].items():
            if i in (corr.get(genre) or {}) and i not in bloques and (envoye.get(genre) or {}).get(i) != h:
                ids.append(i)
    return ids
