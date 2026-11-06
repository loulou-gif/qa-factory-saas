# -*- coding: utf-8 -*-
"""Manuel utilisateur depuis l'application web (temps B) : préparation, contrôle et mise en page.

1. preparer()   : fiche de rédaction 04-livrables/manuel/<redaction>/redaction.json (fonctionnalités et cas
                  validés, lien, comptes par le nom de leur secret, actions autorisées, navigateur).
2. L'assistant (commande /rediger-manuel, skill redaction-manuel) parcourt l'application avec le navigateur
   de la tâche, enregistre ses captures dans <redaction>/captures/ et écrit <redaction>/contenu.json.
3. construire() : contrôle le contenu (structure, captures existantes, aucun secret), puis le met en page
   dans le modèle Word de l'entreprise s'il a été déposé, sinon dans le modèle interne
   (templates/manuel/modele_manuel.docx, générateur templates/manuel/generation/build_manual.py).

Le contenu est une donnée JSON, jamais du code : rien de ce qu'écrit l'assistant n'est exécuté.

Format de contenu.json :
{
  "titre": "Manuel d'utilisation – SauceDemo",
  "sous_titre": "Boutique en ligne",
  "blocs": [
    {"type": "titre", "niveau": 1, "texte": "Préambule", "numerote": false},
    {"type": "paragraphe", "texte": "Texte, **gras** et *italique* permis."},
    {"type": "procedure", "texte": "Se connecter"},
    {"type": "etapes", "elements": ["Ouvrir le lien de l'application.", "Saisir l'identifiant."]},
    {"type": "liste", "elements": ["…"]},
    {"type": "capture", "fichier": "connexion-formulaire.png", "legende": "Page de connexion"},
    {"type": "note", "libelle": "Remarque", "texte": "…"}
  ],
  "couverture": [{"fonctionnalite": "Authentification", "cas": ["CT0001"], "etat": "verifie"}],
  "points_a_confirmer": ["Libellé du bouton de paiement non observé (action non autorisée)."]
}
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
from qa_commun import RACINE, TEMPLATES, charger_projet, fonctionnalites, journaliser, slug  # noqa: E402

MODELE_INTERNE = TEMPLATES / "manuel" / "modele_manuel.docx"
GENERATEUR_INTERNE = TEMPLATES / "manuel" / "generation" / "build_manual.py"
CONTENU_INTERNE = TEMPLATES / "manuel" / "generation" / "contenu_json.py"
TYPES_BLOCS = {"titre", "paragraphe", "procedure", "etapes", "liste", "capture", "note"}
ETATS = {"verifie": "Vérifié dans l'application", "partiel": "Vérifié en partie", "non_verifie": "Non vérifié"}
RE_CAPTURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png$")
CAPTURE_MAX = 10 * 1024 * 1024
BLOCS_MAX = 2000


class ErreurManuel(Exception):
    pass


def dossier_manuel(d: Path) -> Path:
    return d / "04-livrables" / "manuel"


def dossier_redaction(d: Path, ident: str) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}", ident or ""):
        raise ErreurManuel("Rédaction introuvable.")
    g = dossier_manuel(d) / "redactions" / ident
    if not g.is_dir():
        raise ErreurManuel("Rédaction introuvable.")
    return g


def preparer(code: str, url: str, comptes=(), actions: str = "lecture-seule", par: str = "", navigateur: str = "",
             fonctions=None) -> Path:
    d, fiche = charger_projet(code)
    f = d / "03-valide" / "cas-de-tests.json"
    if not f.exists():
        raise ErreurManuel("Les cas doivent être validés avant la rédaction du manuel.")
    data = json.loads(f.read_text(encoding="utf-8"))
    choisies = [x for x in fonctionnalites(data) if not fonctions or x in fonctions]
    if not choisies:
        raise ErreurManuel("Aucune fonctionnalité à décrire.")
    depart = datetime.now().strftime("%Y%m%d-%H%M%S")
    ident, n = depart, 1
    while (dossier_manuel(d) / "redactions" / ident).exists():
        ident, n = f"{depart[:-2]}{(int(depart[-2:]) + n) % 60:02d}", n + 1
    g = dossier_manuel(d) / "redactions" / ident
    (g / "captures").mkdir(parents=True)
    cas = data.get("cas_de_tests") or []
    fiche_r = {
        "id": ident, "debut": datetime.now().isoformat(timespec="seconds"), "par": par,
        "projet": fiche.get("nom") or code, "url": url, "actions": actions, "navigateur": navigateur,
        "comptes": [{"role": lib, "identifiant": f"COMPTE_{i}_IDENTIFIANT", "mot_de_passe": f"COMPTE_{i}_MOT_DE_PASSE"}
                    for i, lib in enumerate(comptes, start=1)],
        "fonctionnalites": [{"nom": fn, "cas": [{"id": c["id"], "titre": c.get("titre", ""), "type": c.get("type", "")}
                                                 for c in cas if c.get("fonctionnalite") == fn]} for fn in choisies],
        "captures": f"04-livrables/manuel/redactions/{ident}/captures",
        "contenu": f"04-livrables/manuel/redactions/{ident}/contenu.json",
    }
    (g / "redaction.json").write_text(json.dumps(fiche_r, ensure_ascii=False, indent=2), encoding="utf-8")
    return g


def _texte(v, limite=4000) -> str:
    if not isinstance(v, str):
        raise ValueError("texte attendu")
    return v.replace("\r", "")[:limite].strip()


def controler_contenu(g: Path, secrets=()) -> tuple:
    """(contenu nettoyé, avertissements) ; ErreurManuel si le contenu est absent ou inutilisable."""
    f = g / "contenu.json"
    if not f.exists():
        raise ErreurManuel("L'assistant n'a pas écrit le contenu du manuel (contenu.json absent).")
    try:
        brut = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ErreurManuel(f"Contenu du manuel illisible (JSON invalide : {e}).")
    if not isinstance(brut, dict) or not isinstance(brut.get("blocs"), list):
        raise ErreurManuel("Contenu du manuel sans liste de blocs.")
    secrets = [s for s in secrets if s and len(str(s)) >= 3]
    avert, masques = [], [0]

    def propre(v, limite=4000):
        t = _texte(v, limite)
        for s in secrets:
            if s in t:
                t = t.replace(s, "<secret>")
                masques[0] += 1
        return t

    blocs, captures = [], g / "captures"
    for i, b in enumerate(brut["blocs"][:BLOCS_MAX], start=1):
        try:
            t = b.get("type")
            if t not in TYPES_BLOCS:
                raise ValueError(f"type inconnu « {t} »")
            if t == "titre":
                blocs.append({"type": t, "niveau": max(1, min(3, int(b.get("niveau") or 1))), "texte": propre(b["texte"], 200),
                              "numerote": b.get("numerote") is not False})
            elif t in ("paragraphe", "procedure"):
                blocs.append({"type": t, "texte": propre(b["texte"], 4000 if t == "paragraphe" else 300)})
            elif t in ("etapes", "liste"):
                el = [propre(x, 1000) for x in (b.get("elements") or [])[:60] if isinstance(x, str) and x.strip()]
                if el:
                    blocs.append({"type": t, "elements": el})
            elif t == "note":
                blocs.append({"type": t, "libelle": propre(b.get("libelle") or "Remarque", 60), "texte": propre(b["texte"])})
            elif t == "capture":
                nom = str(b.get("fichier") or "").strip()
                nom = nom.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                if not nom.lower().endswith(".png"):
                    nom += ".png"
                c = captures / nom
                if not RE_CAPTURE.match(nom) or not c.is_file():
                    avert.append(f"Capture « {nom} » introuvable : figure retirée.")
                    continue
                if c.stat().st_size > CAPTURE_MAX or c.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                    avert.append(f"Capture « {nom} » trop lourde ou qui n'est pas une image PNG : figure retirée.")
                    continue
                blocs.append({"type": t, "fichier": nom, "legende": propre(b.get("legende") or "", 300)})
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            avert.append(f"Bloc {i} ignoré ({e.__class__.__name__ if not str(e) else e}).")
    if not any(b["type"] == "titre" for b in blocs) or len(blocs) < 3:
        raise ErreurManuel("Le contenu du manuel est vide ou presque : aucun chapitre exploitable.")
    points = [propre(p, 600) for p in (brut.get("points_a_confirmer") or [])[:200] if isinstance(p, str) and p.strip()]
    couverture = []
    for c in (brut.get("couverture") or [])[:200]:
        if isinstance(c, dict) and isinstance(c.get("fonctionnalite"), str):
            couverture.append({"fonctionnalite": propre(c["fonctionnalite"], 200),
                               "cas": [str(x)[:20] for x in (c.get("cas") or [])[:100]],
                               "etat": c.get("etat") if c.get("etat") in ETATS else "non_verifie"})
    if masques[0]:
        avert.append(f"{masques[0]} valeur(s) de compte de test retirée(s) du texte.")
    contenu = {"projet": "", "titre": propre(brut.get("titre") or "", 200), "sous_titre": propre(brut.get("sous_titre") or "", 120),
               "blocs": blocs, "points_a_confirmer": points, "couverture": couverture}
    return contenu, avert


def _points_md(fiche_r: dict, contenu: dict, avert: list) -> str:
    lignes = [f"# Points à confirmer – manuel utilisateur {fiche_r.get('projet', '')}", "",
              f"Rédaction {fiche_r['id']} sur {fiche_r.get('url', '')}.", "", "## Couverture", "",
              "| Fonctionnalité | Cas | État |", "|---|---|---|"]
    for c in contenu["couverture"]:
        lignes.append(f"| {c['fonctionnalite']} | {', '.join(c['cas'])} | {ETATS[c['etat']]} |")
    lignes += ["", "## Points à confirmer", ""] + [f"- {p}" for p in contenu["points_a_confirmer"] or ["Aucun."]]
    if avert:
        lignes += ["", "## Contrôles de QA Factory", ""] + [f"- {a}" for a in avert]
    return "\n".join(lignes) + "\n"


def construire(code: str, ident: str, modele_entreprise: Path = None, secrets=()) -> dict:
    """Contrôle le contenu de la rédaction et produit le .docx ; renvoie la synthèse (écrite dans synthese.json)."""
    d, fiche = charger_projet(code)
    g = dossier_redaction(d, ident)
    fiche_r = json.loads((g / "redaction.json").read_text(encoding="utf-8"))
    contenu, avert = controler_contenu(g, secrets)
    contenu["projet"] = fiche.get("nom") or code
    if not contenu["titre"]:
        contenu["titre"] = f"Manuel d'utilisation – {contenu['projet']}"
    (g / "contenu.controle.json").write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
    version = (fiche.get("manuel") or {}).get("version") or "V1.0"
    sortie = g / f"Manuel_utilisateur_{slug(contenu['projet']).replace('-', '_')}_{version}.docx"
    if modele_entreprise and Path(modele_entreprise).is_file():
        import manuel_modele
        try:
            r = manuel_modele.generer(modele_entreprise, contenu, g / "captures", sortie,
                                      manuel_modele.valeurs_defaut(contenu, fiche))
        except manuel_modele.ErreurModele as e:
            raise ErreurManuel(f"Mise en page dans le modèle de l'entreprise impossible : {e}")
        modele = "entreprise"
    else:
        env = {**os.environ, "QAF_CONTENU_MANUEL": str(g / "contenu.controle.json")}
        p = subprocess.run([sys.executable, str(GENERATEUR_INTERNE), str(MODELE_INTERNE), str(g / "captures"), str(sortie),
                            str(CONTENU_INTERNE)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, cwd=str(RACINE), timeout=300)
        if p.returncode:
            raise ErreurManuel("Mise en page dans le modèle interne impossible : " + (p.stderr or p.stdout)[-400:])
        r = {"figures": sum(1 for b in contenu["blocs"] if b["type"] == "capture")}
        modele = "interne"
    (g / "points_a_confirmer_manuel.md").write_text(_points_md(fiche_r, contenu, avert), encoding="utf-8")
    synthese = {"redaction": fiche_r["id"], "debut": fiche_r["debut"], "fin": datetime.now().isoformat(timespec="seconds"),
                "url": fiche_r.get("url"), "par": fiche_r.get("par"), "modele": modele, "fichier": sortie.name,
                "chemin": str(sortie.relative_to(d)).replace("\\", "/"),
                "points": str((g / "points_a_confirmer_manuel.md").relative_to(d)).replace("\\", "/"),
                "figures": r.get("figures", 0), "chapitres": sum(1 for b in contenu["blocs"] if b["type"] == "titre" and b["niveau"] == 1),
                "procedures": sum(1 for b in contenu["blocs"] if b["type"] == "procedure"),
                "points_a_confirmer": contenu["points_a_confirmer"][:50], "couverture": contenu["couverture"],
                "avertissements": avert}
    (g / "synthese.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=2), encoding="utf-8")
    journaliser(d, "manuel", f"{synthese['chapitres']} chapitre(s), {synthese['figures']} figure(s), modèle {modele}",
                [synthese["chemin"]])
    return synthese


def redactions(code: str) -> list:
    """Rédactions terminées, la plus récente d'abord."""
    d, _ = charger_projet(code)
    base = dossier_manuel(d) / "redactions"
    res = []
    for g in sorted(base.iterdir(), reverse=True) if base.exists() else []:
        try:
            res.append(json.loads((g / "synthese.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return res


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("projet")
    p.add_argument("redaction")
    p.add_argument("--modele", help="modèle Word de l'entreprise (sinon modèle interne)")
    a = p.parse_args()
    try:
        print(json.dumps(construire(a.projet, a.redaction, Path(a.modele) if a.modele else None), ensure_ascii=False, indent=2))
    except ErreurManuel as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)
