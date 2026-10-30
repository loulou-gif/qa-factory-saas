# -*- coding: utf-8 -*-
"""Crée l'arborescence d'un nouveau projet QA.

Usage : python outils/nouveau_projet.py <nom> [--url URL] [--squash-id ID] [--squash-nom NOM]
"""
import argparse
import json
import re

from qa_commun import DOSSIERS, PROJETS, erreur, journaliser


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("nom", help="nom court du projet, sans espace (ex. saucedemo)")
    p.add_argument("--url", default="", help="URL de l'application à tester")
    p.add_argument("--squash-id", type=int, default=None, help="ID du projet dans Squash TM")
    p.add_argument("--squash-nom", default="", help="nom du projet dans Squash TM")
    p.add_argument("--libelle", default="", help="nom lisible (ex. « SauceDemo »)")
    p.add_argument("--responsable", default="", help="testeur responsable du projet (celui qui valide)")
    a = p.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.nom):
        erreur("le nom doit être en minuscules, chiffres et tirets (ex. orange-efacture)")
    d = PROJETS / a.nom
    if d.exists():
        erreur(f"{d} existe déjà")

    for sous in DOSSIERS:
        (d / sous).mkdir(parents=True)
    for sous in ("squash", "cahier", "specs", "manuel", "exploration"):
        (d / "04-livrables" / sous).mkdir()
        (d / "04-livrables" / sous / ".gitkeep").touch()
    (d / "03-valide" / ".gitkeep").touch()

    libelle = a.libelle or a.nom
    projet = {
        "nom": libelle,
        "code": a.nom,
        "client": "À renseigner",
        "responsable": a.responsable or "À renseigner",
        "langue": "fr",
        "application": {
            "type": "web",
            "url": a.url,
            "environnement": "À confirmer",
            "actions_autorisees": "lecture seule tant que l'environnement et les données de test ne sont pas confirmés",
            "variables_identifiants": ["APP_USERNAME", "APP_PASSWORD"]
        },
        "squash": {
            "projet_id": a.squash_id,
            "projet_nom": a.squash_nom or libelle,
            "ranger_par_fonctionnalite": True,
            "dossier_parent_exigences_id": None,
            "dossier_parent_cas_id": None
        },
        "cahier": {
            "titre": f"CAHIER DE TESTS {libelle.upper()}",
            "version": "V1.0",
            "auteur": "À renseigner",
            "contact": "À renseigner",
            "description": "À renseigner",
            "nominaux_uniquement": False
        },
        "automatisation": {
            "depot": "",
            "note": "chemin du dépôt Playwright du projet (temps B)"
        }
    }
    (d / "projet.json").write_text(json.dumps(projet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "01-entrant" / "LISEZMOI.md").write_text(
        "# Documents d'entrée\n\nDéposer ici le cahier des charges, les User Stories, le DSF, les maquettes "
        "(PDF, DOCX, MD, images).\nPuis lancer `/analyser " + a.nom + "` dans Claude Code ou OpenCode.\n", encoding="utf-8")
    (d / "02-a-valider" / "LISEZMOI.md").write_text(
        "# À valider\n\nL'agent écrit ici le résultat de l'analyse. Relire `cas-de-tests.md` (ou `cas-de-tests.xlsx`, "
        "ou `cas-de-tests.docx`), `ambiguites.md` et `jeux-de-donnees.md`.\n"
        "Pour corriger : modifier l'Excel OU le Word puis `/corriger " + a.nom + "`, ou `/corriger " + a.nom + " <demande>`.\n"
        "Pour valider : DÉPLACER tout le contenu de ce dossier dans `03-valide/`.\n", encoding="utf-8")
    journaliser(d, "nouveau-projet", "projet créé", ["projet.json"])
    print(f"Projet créé : {d}")
    print("À compléter dans projet.json : client, environnement, ID Squash, auteur et contact du cahier.")


if __name__ == "__main__":
    main()
