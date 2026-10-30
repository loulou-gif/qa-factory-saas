# -*- coding: utf-8 -*-
"""Génère les vues des cas de tests à partir de cas-de-tests.json.

Usage : python outils/rendre_revue.py <projet> [--dossier 02-a-valider|03-valide]

- cas-de-tests.md   : vue de relecture, en lecture seule ;
- cas-de-tests.xlsx : version Excel modifiable ;
- cas-de-tests.docx : version Word modifiable ;
- .synchro.json     : état à la génération (sert à repérer le fichier modifié ensuite).

Ne pas lancer après une modification de l'Excel ou du Word : les modifications seraient
écrasées. Utiliser outils/synchroniser_vues.py, qui les importe d'abord.

Le fichier produit porte l'empreinte du JSON : le contrôle détecte ainsi une vue
modifiée à la main ou non régénérée après une correction du JSON.
"""
import argparse
import json
from collections import Counter

import vues_cas

from qa_commun import (TECHNIQUES, TYPES_CHANGEMENT, TYPES_TEST, charger_cas, charger_projet, empreinte, erreur,
                       fonctionnalites, lire_questions)

TYPES = {"nominal": "Nominal", "negatif": "Négatif", "limite": "Limite"}
DECISIONS = {"retenu": "Retenu", "non-retenu": "Non retenu", "a-confirmer": "À confirmer"}
APPROCHES = {"cas": "Cas de tests de ce fichier", "campagne-dediee": "Campagne dédiée", "checklist": "Checklist",
             "exploratoire": "Sessions exploratoires"}


def libelle_type(tt):
    return TYPES_TEST[tt][0] if tt in TYPES_TEST else TYPES_CHANGEMENT.get(tt, tt or "")


def libelle_technique(t):
    return f"{TECHNIQUES[t][0]} ({TECHNIQUES[t][1]})" if t in TECHNIQUES else (t or "")


def cellule(t):
    return str(t or "").replace("|", "\\|").replace("\n", "<br>")


def vues_modifiees(base):
    """Vues Excel/Word modifiées depuis leur génération (noms de fichiers), d'après .synchro.json."""
    etat = base / ".synchro.json"
    if not etat.exists():
        return []
    snap = json.loads(etat.read_text(encoding="utf-8"))["projection"]
    res = []
    for nom, lire in (("cas-de-tests.xlsx", vues_cas.lire_xlsx), ("cas-de-tests.docx", vues_cas.lire_docx)):
        f = base / nom
        if f.exists():
            try:
                if lire(f) != snap:
                    res.append(nom)
            except ImportError:
                continue
            except Exception as e:
                res.append(f"{nom} (illisible : {e})")
    return res


def rendre(projet_nom, dossier, forcer=False):
    d, projet = charger_projet(projet_nom)
    base = d / dossier
    fjson = base / "cas-de-tests.json"
    data = charger_cas(fjson)
    if not forcer:
        modifiees = vues_modifiees(base)
        if modifiees:
            erreur(f"{', '.join(modifiees)} {'contiennent' if len(modifiees) > 1 else 'contient'} des modifications non reportées dans le JSON : les régénérer les "
                   f"effacerait. Lancer : python outils/synchroniser_vues.py {projet_nom} (ou /corriger {projet_nom}). "
                   "Pour les écraser volontairement : --forcer")
    questions = lire_questions(base / "ambiguites.md")
    exigences = data.get("exigences", [])
    cas = data.get("cas_de_tests", [])
    meta = data.get("meta", {})

    lignes = [
        f"<!-- Fichier généré par outils/rendre_revue.py à partir de cas-de-tests.json — NE PAS MODIFIER. empreinte: {empreinte(fjson)} -->",
        f"# Cas de tests — {projet.get('nom', projet_nom)} (version {meta.get('version', '?')})",
        "",
        "Vue de relecture, en lecture seule. Pour modifier : `cas-de-tests.xlsx` ou `cas-de-tests.docx` (l'un ou l'autre), puis `/corriger " + projet_nom + "` ; ou directement `/corriger " + projet_nom + " <demande>`.",
        "",
        f"Sources analysées : {', '.join(meta.get('sources', [])) or 'non renseignées'}",
        "",
        "## Synthèse",
        "",
        "| Indicateur | Valeur |",
        "|---|---|",
        f"| Fonctionnalités | {len(fonctionnalites(data))} |",
        f"| Exigences | {len(exigences)} |",
        f"| Cas de tests | {len(cas)} |",
    ]
    for t, n in sorted(Counter(c.get("type", "?") for c in cas).items()):
        lignes.append(f"| Cas {TYPES.get(t, t).lower()} | {n} |")
    for t, n in sorted(Counter(c.get("type_test", "?") for c in cas).items()):
        lignes.append(f"| Type de test : {libelle_type(t).lower()} | {n} |")
    for t, n in sorted(Counter(c.get("technique", "?") for c in cas).items()):
        lignes.append(f"| Technique : {libelle_technique(t)} | {n} |")
    ouvertes = [q for q in questions.values() if q["statut"] == "ouverte"]
    bloquantes = [qid for qid, q in questions.items() if q["statut"] == "ouverte" and q["gravite"] == "bloquante"]
    lignes += [
        f"| Questions ouvertes | {len(ouvertes)} (dont bloquantes : {len(bloquantes)}) |",
        "",
    ]

    strat = data.get("strategie_tests") or []
    if strat:
        lignes += ["## Stratégie de types de tests (ISTQB)", "",
                   "Chaque type de test ISTQB est examiné : retenu, non retenu (avec la raison) ou à confirmer (avec une question).", "",
                   "| ID | Type de test | Décision | Niveau | Approche | Objectif | Exigences | Cas | Outil | Justification | Questions |",
                   "|---|---|---|---|---|---|---|---|---|---|---|"]
        for t in strat:
            lignes.append(" | ".join([
                f"| {t.get('id', '')}", libelle_type(t.get("type_test")), DECISIONS.get(t.get("decision"), t.get("decision", "")),
                cellule(t.get("niveau", "")), APPROCHES.get(t.get("approche"), cellule(t.get("approche", ""))),
                cellule(t.get("objectif", "")), ", ".join(t.get("exigences", [])), ", ".join(t.get("cas", [])),
                cellule(t.get("outil", "")), cellule(t.get("justification", "")), ", ".join(t.get("questions", [])) + " |"]))
        lignes.append("")

    for f in fonctionnalites(data):
        lignes += [f"## {f}", "", "### Exigences", "", "| ID | Exigence | Criticité | Source | Questions |", "|---|---|---|---|---|"]
        for e in (x for x in exigences if x.get("fonctionnalite") == f):
            lignes.append(f"| {e['id']} | **{cellule(e.get('titre'))}**<br>{cellule(e.get('description'))} | "
                          f"{e.get('criticite', 'MAJOR')} | {cellule(e.get('source'))} | {', '.join(e.get('questions', []))} |")
        lignes += ["", "### Cas de tests", ""]
        for c in (x for x in cas if x.get("fonctionnalite") == f):
            alerte = ""
            if any(q in bloquantes for q in c.get("questions", [])):
                alerte = " — **suspendu à une question bloquante**"
            lignes += [
                f"#### {c['id']} — {c.get('titre', '')}{alerte}",
                "",
                f"- **Exigences** : {', '.join(c.get('exigences', []))}",
                f"- **Nature** : {TYPES.get(c.get('type'), c.get('type'))} — **Type de test** : {libelle_type(c.get('type_test'))} — **Importance** : {c.get('importance', 'MEDIUM')}",
                f"- **Technique ISTQB** : {libelle_technique(c.get('technique'))}",
                f"- **Prérequis** : {cellule(c.get('prerequis'))}",
            ]
            if c.get("description"):
                lignes.append(f"- **Objectif** : {cellule(c['description'])}")
            if c.get("jeux_de_donnees"):
                lignes.append(f"- **Jeux de données** : {', '.join(c['jeux_de_donnees'])}")
            if c.get("questions"):
                lignes.append(f"- **Questions liées** : {', '.join(c['questions'])}")
            lignes += ["", "| # | Action | Résultat attendu |", "|---|---|---|"]
            for i, s in enumerate(c.get("etapes", []), start=1):
                lignes.append(f"| {i} | {cellule(s.get('action'))} | {cellule(s.get('resultat_attendu'))} |")
            lignes.append("")

    sortie = base / "cas-de-tests.md"
    sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    ecrire_vues(base, data, projet.get("nom", projet_nom))
    (base / ".synchro.json").write_text(json.dumps({"empreinte_json": empreinte(fjson),
                                                    "projection": vues_cas.projection(data)},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return sortie, len(exigences), len(cas)


def ecrire_vues(base, data, nom):
    for nom_fichier, fonction in (("cas-de-tests.xlsx", vues_cas.ecrire_xlsx), ("cas-de-tests.docx", vues_cas.ecrire_docx)):
        cible = base / nom_fichier
        try:
            fonction(data, nom, cible)
        except PermissionError:
            erreur(f"{cible} est ouvert dans une autre application : le fermer puis relancer")
        except ImportError:
            erreur("bibliothèque manquante : pip install openpyxl python-docx")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("projet")
    p.add_argument("--dossier", default="02-a-valider", choices=["02-a-valider", "03-valide"])
    p.add_argument("--forcer", action="store_true", help="écraser les modifications non importées de l'Excel et du Word")
    a = p.parse_args()
    sortie, ne, nc = rendre(a.projet, a.dossier, a.forcer)
    print(f"{sortie} : {ne} exigences, {nc} cas de tests (+ cas-de-tests.xlsx, cas-de-tests.docx)")


if __name__ == "__main__":
    main()
