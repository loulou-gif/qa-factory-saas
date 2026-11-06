# -*- coding: utf-8 -*-
"""Cahier de tests au modèle Excel d'une entreprise (déposé dans l'application, page Paramètres).

Usage : python outils/cahier_modele.py analyser <modele.xlsx>
        python outils/cahier_modele.py generer <projet> <modele.xlsx> [--nominaux]

Le modèle est un classeur .xlsx ordinaire. Rien à programmer :
- **Tableau des cas** : une ligne d'en-têtes dont les libellés sont reconnus (« ID », « Prérequis »,
  « Action », « Résultat attendu », « Statut »…, voir COLONNES). Les lignes situées sous les en-têtes
  sont remplacées par les cas validés ; la mise en forme de la première ligne sous les en-têtes sert
  de modèle aux lignes écrites. Avec une colonne d'étapes (« Action », « Étape »…) : une ligne par
  étape, les colonnes du cas fusionnées sur ses étapes ; sinon une ligne par cas.
- **Marqueurs** n'importe où dans le classeur : {{PROJET}}, {{TITRE}}, {{VERSION}}, {{DATE}},
  {{AUTEUR}}, {{CONTACT}}, {{CLIENT}}, {{URL}}, {{DESCRIPTION}}, {{NB_CAS}}, {{ENVIRONNEMENT}}.
- Les colonnes de résultat (« Résultat obtenu », « Statut », « Commentaire ») restent vides : elles se
  remplissent pendant la recette, jamais sans exécution observée.

Le modèle n'est jamais exécuté : pas de macro (.xlsm refusé), formules laissées telles quelles.
"""
import argparse
import json
import math
import re
import sys
import unicodedata
import zipfile
from copy import copy
from datetime import date
from pathlib import Path

TAILLE_MAX = 15 * 1024 * 1024          # fichier déposé
DECOMPRESSE_MAX = 150 * 1024 * 1024    # contenu décompressé (protection contre les archives piégées)
LIGNES_ANALYSEES = 80
HAUTEUR_LIGNE = 15.0

# Champ -> libellés d'en-tête reconnus (comparés sans accents, sans casse ni ponctuation).
COLONNES = {
    "id": ["id", "identifiant", "ref", "reference", "n", "no", "num", "numero", "code", "id cas", "id test", "id du cas",
           "reference du cas", "ref cas", "id cas de test", "n cas", "numero du cas"],
    "fonctionnalite": ["fonctionnalite", "fonctionnalites", "module", "modules", "domaine", "rubrique", "theme", "menu",
                       "fonction", "perimetre", "sous module", "ecran"],
    "titre": ["titre", "intitule", "objectif", "cas de test", "cas de tests", "scenario", "nom", "libelle", "nom du cas",
              "titre du cas", "intitule du cas", "description du cas", "description du test", "objectif du test", "description"],
    "prerequis": ["prerequis", "pre requis", "precondition", "preconditions", "pre condition", "pre conditions",
                  "conditions prealables", "condition prealable", "contexte", "situation initiale"],
    "numero_etape": ["n etape", "no etape", "numero etape", "numero de l etape", "etape n", "pas"],
    "action": ["etape", "etapes", "action", "actions", "description de l etape", "procedure", "pas de test", "deroulement",
               "action a realiser", "actions a realiser", "etapes de test", "description des etapes", "operations"],
    "attendu": ["resultat attendu", "resultats attendus", "attendu", "comportement attendu", "resultat escompte"],
    "donnees": ["donnees", "donnees de test", "jeu de donnees", "jeux de donnees", "donnee", "jdd", "donnees d entree"],
    "priorite": ["priorite", "importance", "criticite"],
    "type": ["type", "nature", "type de test", "type de cas"],
    "exigences": ["exigence", "exigences", "ref exigence", "reference exigence", "exigences couvertes", "ref exigences"],
    "obtenu": ["resultat obtenu", "resultats obtenus", "resultat", "resultats", "resultat observe", "observe", "constat"],
    "statut": ["statut", "verdict", "etat", "ok ko", "ok nok", "conforme", "conformite", "decision"],
    "commentaire": ["commentaire", "commentaires", "remarque", "remarques", "observation", "observations", "anomalie",
                    "anomalies", "ticket", "n anomalie"],
}
LIBELLES = {"id": "Identifiant", "fonctionnalite": "Fonctionnalité", "titre": "Titre du cas", "prerequis": "Prérequis",
            "numero_etape": "N° d'étape", "action": "Action (une ligne par étape)", "attendu": "Résultat attendu",
            "donnees": "Jeux de données", "priorite": "Priorité", "type": "Type de cas", "exigences": "Exigences",
            "obtenu": "Résultat obtenu (laissé vide)", "statut": "Statut (laissé vide)", "commentaire": "Commentaire (laissé vide)"}
VIDES = ("obtenu", "statut", "commentaire")
NIVEAU_CAS = ("id", "fonctionnalite", "titre", "prerequis", "donnees", "priorite", "type", "exigences")
MARQUEURS = ("PROJET", "TITRE", "VERSION", "DATE", "AUTEUR", "CONTACT", "CLIENT", "URL", "DESCRIPTION", "NB_CAS", "ENVIRONNEMENT")
RE_MARQUEUR = re.compile(r"\{\{\s*([A-Z_]+)\s*\}\}")
IMPORTANCES = {"VERY_HIGH": "Très haute", "HIGH": "Haute", "MEDIUM": "Moyenne", "LOW": "Basse"}
TYPES = {"nominal": "Nominal", "negatif": "Négatif", "limite": "Limite"}


class ErreurModele(Exception):
    pass


def normaliser(texte) -> str:
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\(.*?\)", " ", t)          # « Résultat attendu (expected) »
    t = re.sub(r"[^a-z0-9]+", " ", t)
    # Pluriels ignorés mot à mot : « Résultats attendu », « Résultat attendus »…
    return " ".join(m[:-1] if len(m) > 3 and m.endswith("s") else m for m in t.split())


_INDEX = {}
for _champ, _libs in COLONNES.items():
    for _l in _libs:
        _INDEX.setdefault(normaliser(_l), _champ)


def champ_de(entete) -> str:
    n = normaliser(entete)
    if not n or len(n) > 60:
        return ""
    if n in _INDEX:
        return _INDEX[n]
    for prefixe in ("resultat attendu", "resultat obtenu", "pre requis", "prerequis", "jeu de donnees", "donnees de test"):
        if n.startswith(prefixe):
            return _INDEX[normaliser(prefixe)]
    return ""


def verifier_fichier(donnees: bytes):
    """Refuse ce qui n'est pas un classeur .xlsx raisonnable (taille, macros, archive piégée)."""
    if len(donnees) > TAILLE_MAX:
        raise ErreurModele(f"Fichier trop volumineux ({len(donnees) // (1024 * 1024)} Mo, {TAILLE_MAX // (1024 * 1024)} Mo au plus).")
    import io
    try:
        z = zipfile.ZipFile(io.BytesIO(donnees))
    except zipfile.BadZipFile:
        raise ErreurModele("Ce fichier n'est pas un classeur Excel .xlsx (les anciens .xls sont à réenregistrer en .xlsx).")
    noms = z.namelist()
    if "xl/workbook.xml" not in noms:
        raise ErreurModele("Ce fichier n'est pas un classeur Excel .xlsx.")
    if any(n.lower().endswith("vbaproject.bin") for n in noms):
        raise ErreurModele("Le modèle contient des macros : l'enregistrer en classeur sans macro (.xlsx).")
    if sum(i.file_size for i in z.infolist()) > DECOMPRESSE_MAX:
        raise ErreurModele("Classeur trop volumineux une fois décompressé.")


def _charger(source):
    import io
    import openpyxl
    donnees = Path(source).read_bytes() if not isinstance(source, (bytes, bytearray)) else bytes(source)
    verifier_fichier(donnees)
    try:
        return openpyxl.load_workbook(io.BytesIO(donnees))
    except Exception as e:  # noqa: BLE001
        raise ErreurModele(f"Classeur illisible : {e.__class__.__name__}.")


def _valeur_cellule(c):
    v = c.value
    return v if isinstance(v, str) else ""


def trouver_tableau(wb) -> dict:
    """Feuille et ligne d'en-têtes du tableau des cas : la ligne qui reconnaît le plus de colonnes."""
    meilleur = None
    for ws in wb.worksheets:
        fusions_entetes = {}
        for rng in ws.merged_cells.ranges:
            fusions_entetes[(rng.min_row, rng.min_col)] = rng
        for r in range(1, min(ws.max_row, LIGNES_ANALYSEES) + 1):
            colonnes, vus = {}, set()
            for c in range(1, min(ws.max_column, 60) + 1):
                cel = ws.cell(r, c)
                champ = champ_de(_valeur_cellule(cel))
                if not champ or champ in vus:
                    continue
                vus.add(champ)
                colonnes[champ] = {"colonne": c, "entete": str(cel.value).strip()}
            utiles = [k for k in colonnes if k not in VIDES]
            if len(colonnes) < 3 or not ({"titre", "action"} & set(colonnes)):
                continue
            score = (len(utiles), len(colonnes))
            if not meilleur or score > meilleur["score"]:
                meilleur = {"score": score, "feuille": ws.title, "ligne": r, "colonnes": colonnes}
    if not meilleur:
        raise ErreurModele(
            "Tableau des cas introuvable : le modèle doit contenir une ligne d'en-têtes avec au moins trois colonnes "
            "reconnues, dont « Titre » (ou « Description », « Scénario ») ou « Action » (ou « Étape ») ; par exemple "
            "« ID », « Prérequis », « Action », « Résultat attendu », « Statut ».")
    # Titre et description à la fois : « description » sert alors aux prérequis s'ils n'ont pas de colonne.
    return meilleur


def marqueurs_presents(wb) -> list:
    vus = []
    for ws in wb.worksheets:
        for ligne in ws.iter_rows():
            for c in ligne:
                if isinstance(c.value, str):
                    for m in RE_MARQUEUR.findall(c.value):
                        if m not in vus:
                            vus.append(m)
    return vus


def analyser(source) -> dict:
    """Ce que QA Factory fera du modèle : affiché au dépôt, pour que la personne le vérifie."""
    wb = _charger(source)
    t = trouver_tableau(wb)
    ws = wb[t["feuille"]]
    cols = t["colonnes"]
    mode = "etapes" if "action" in cols else "cas"
    from openpyxl.utils import get_column_letter
    colonnes = [{"lettre": get_column_letter(v["colonne"]), "entete": v["entete"], "champ": k, "libelle": LIBELLES[k]}
                for k, v in sorted(cols.items(), key=lambda kv: kv[1]["colonne"])]
    presents = marqueurs_presents(wb)
    avert = []
    if "attendu" not in cols:
        avert.append("Pas de colonne « Résultat attendu » : les résultats attendus ne figureront pas dans le cahier.")
    if "id" not in cols:
        avert.append("Pas de colonne d'identifiant : la traçabilité avec Squash (CT0001…) passera par le titre seulement.")
    if mode == "cas":
        avert.append("Pas de colonne d'étapes (« Action », « Étape ») : une ligne par cas, les étapes et résultats attendus regroupés.")
    inconnus = [m for m in presents if m not in MARQUEURS]
    if inconnus:
        avert.append("Marqueurs non reconnus, laissés tels quels : " + ", ".join("{{" + m + "}}" for m in inconnus) + ".")
    exemples = max(0, ws.max_row - t["ligne"])
    return {"feuille": t["feuille"], "ligne_entetes": t["ligne"], "mode": mode, "colonnes": colonnes,
            "marqueurs": [m for m in presents if m in MARQUEURS], "lignes_remplacees": exemples, "avertissements": avert}


# ---------------------------------------------------------------- génération

def _lignes(texte, largeur) -> int:
    if not texte:
        return 1
    par_ligne = max(int((largeur or 12) * 1.15), 1)
    return sum(max(1, math.ceil(len(p) / par_ligne)) for p in str(texte).split("\n"))


def valeurs_projet(fiche: dict, nb_cas: int) -> dict:
    conf, app = fiche.get("cahier") or {}, fiche.get("application") or {}
    nom = fiche.get("nom") or fiche.get("code") or "Projet"
    inconnu = lambda v: v if v and "renseigner" not in str(v).lower() else "À renseigner"  # noqa: E731
    return {"PROJET": nom, "TITRE": conf.get("titre") or f"Cahier de tests {nom}", "VERSION": conf.get("version") or "V1.0",
            "DATE": date.today().strftime("%d/%m/%Y"), "AUTEUR": inconnu(conf.get("auteur")), "CONTACT": inconnu(conf.get("contact")),
            "CLIENT": inconnu(fiche.get("client")), "URL": app.get("url") or "À renseigner",
            "DESCRIPTION": inconnu(conf.get("description")), "NB_CAS": str(nb_cas),
            "ENVIRONNEMENT": inconnu(app.get("environnement"))}


def remplacer_marqueurs(wb, valeurs: dict):
    for ws in wb.worksheets:
        for ligne in ws.iter_rows():
            for c in ligne:
                if isinstance(c.value, str) and "{{" in c.value:
                    nouveau = RE_MARQUEUR.sub(lambda m: valeurs.get(m.group(1), m.group(0)), c.value)
                    if nouveau != c.value:
                        c.value = nouveau
    t = wb.properties
    if t.title and "{{" in t.title:
        t.title = RE_MARQUEUR.sub(lambda m: valeurs.get(m.group(1), m.group(0)), t.title)


def valeur_cas(champ, c, jeux_libelles=None):
    if champ == "id":
        return c.get("id")
    if champ == "fonctionnalite":
        return c.get("fonctionnalite")
    if champ == "titre":
        return c.get("titre")
    if champ == "prerequis":
        return c.get("prerequis")
    if champ == "donnees":
        return ", ".join(c.get("jeux_de_donnees") or []) or None
    if champ == "priorite":
        return IMPORTANCES.get(c.get("importance"), c.get("importance"))
    if champ == "type":
        return TYPES.get(c.get("type"), c.get("type"))
    if champ == "exigences":
        return ", ".join(c.get("exigences") or []) or None
    return None


def remplir(wb, cas: list, analyse_tableau: dict) -> int:
    ws = wb[analyse_tableau["feuille"]]
    entete = analyse_tableau["ligne"]
    cols = {k: v["colonne"] for k, v in analyse_tableau["colonnes"].items()}
    premiere = entete + 1
    col_min, col_max = min(cols.values()), max(cols.values())
    from openpyxl.utils import get_column_letter
    largeurs = {c: ws.column_dimensions[get_column_letter(c)].width or 12 for c in range(col_min, col_max + 1)}

    # Mise en forme de référence : la première ligne sous les en-têtes, ou à défaut celle des en-têtes sans gras ni fond.
    proto = {}
    for c in range(col_min, col_max + 1):
        src = ws.cell(premiere, c)
        if not src.has_style:
            src = ws.cell(entete, c)
            font = copy(src.font)
            font.b = False
            proto[c] = (font, None, copy(src.border), None, src.number_format)
        else:
            proto[c] = (copy(src.font), copy(src.fill), copy(src.border), copy(src.alignment), src.number_format)
    from openpyxl.styles import Alignment

    # Lignes d'exemple du modèle : valeurs, fusions et hauteurs effacées dans les colonnes du tableau.
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= premiere and rng.max_col >= col_min and rng.min_col <= col_max:
            ws.unmerge_cells(str(rng))
    for r in range(premiere, ws.max_row + 1):
        for c in range(col_min, col_max + 1):
            ws.cell(r, c).value = None
        ws.row_dimensions[r].height = None

    def styler(cel, c):
        font, fill, border, alignment, fmt = proto[c]
        cel.font, cel.border, cel.number_format = copy(font), copy(border), fmt
        if fill is not None:
            cel.fill = copy(fill)
        al = copy(alignment) if alignment is not None else Alignment()
        cel.alignment = Alignment(horizontal=al.horizontal, vertical=al.vertical or "center", wrap_text=True)

    etapes_mode = "action" in cols
    r = premiere
    for c in cas:
        etapes = c.get("etapes") or [{}]
        haut = r
        n = len(etapes) if etapes_mode else 1
        hauteurs = {}
        for i in range(n):
            ligne = r + i
            for col in range(col_min, col_max + 1):
                styler(ws.cell(ligne, col), col)
            if etapes_mode:
                e = etapes[i]
                ws.cell(ligne, cols["action"]).value = (e.get("action") or "") if "numero_etape" in cols else f"{i + 1}- {e.get('action') or ''}"
                if "numero_etape" in cols:
                    ws.cell(ligne, cols["numero_etape"]).value = i + 1
                if "attendu" in cols:
                    ws.cell(ligne, cols["attendu"]).value = e.get("resultat_attendu") or None
                hauteurs[ligne] = max(_lignes(e.get("action"), largeurs.get(cols["action"])),
                                      _lignes(e.get("resultat_attendu"), largeurs.get(cols.get("attendu")))) * HAUTEUR_LIGNE
            else:
                if "attendu" in cols:
                    ws.cell(ligne, cols["attendu"]).value = "\n".join(
                        f"{j}- {x.get('action', '')} : {x.get('resultat_attendu', '')}" for j, x in enumerate(etapes, 1)) or None
                hauteurs[ligne] = _lignes(ws.cell(ligne, cols["attendu"]).value if "attendu" in cols else "", 30) * HAUTEUR_LIGNE
        bas = r + n - 1
        for champ in NIVEAU_CAS:
            if champ not in cols:
                continue
            col = cols[champ]
            ws.cell(haut, col).value = valeur_cas(champ, c)
            if bas > haut:
                ws.merge_cells(start_row=haut, start_column=col, end_row=bas, end_column=col)
            besoin = _lignes(ws.cell(haut, col).value, largeurs.get(col)) * HAUTEUR_LIGNE
            dispo = sum(hauteurs.values())
            if dispo < besoin:
                hauteurs[bas] += besoin - dispo
        for ligne, h in hauteurs.items():
            ws.row_dimensions[ligne].height = round(min(h + 6, 400), 2)
        r = bas + 1
    return len(cas)


def generer(code: str, modele, nominaux: bool = False, sortie: Path = None):
    """Écrit le cahier du projet au modèle de l'entreprise ; renvoie (fichier, nombre de cas)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from qa_commun import charger_cas, charger_projet, journaliser
    from build_cahier import nom_fichier
    d, fiche = charger_projet(code)
    data = charger_cas(d / "03-valide" / "cas-de-tests.json")
    nominaux = nominaux or (fiche.get("cahier") or {}).get("nominaux_uniquement", False)
    cas = [c for c in data.get("cas_de_tests", []) if not nominaux or c.get("type") == "nominal"]
    if not cas:
        raise ErreurModele("Aucun cas de test à écrire.")
    wb = _charger(modele)
    t = trouver_tableau(wb)
    n = remplir(wb, cas, t)
    remplacer_marqueurs(wb, valeurs_projet(fiche, n))
    out_dir = d / "04-livrables" / "cahier"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = sortie or out_dir / nom_fichier(fiche, nominaux)
    wb.save(out)
    journaliser(d, "cahier", f"{n} cas (modèle de l'entreprise)", [str(out.relative_to(d))])
    return out, n


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)
    a1 = sp.add_parser("analyser")
    a1.add_argument("modele")
    a2 = sp.add_parser("generer")
    a2.add_argument("projet")
    a2.add_argument("modele")
    a2.add_argument("--nominaux", action="store_true")
    a = p.parse_args()
    try:
        if a.action == "analyser":
            print(json.dumps(analyser(a.modele), ensure_ascii=False, indent=2))
        else:
            out, n = generer(a.projet, a.modele, a.nominaux)
            print(f"{out} : {n} cas de tests")
    except ErreurModele as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
