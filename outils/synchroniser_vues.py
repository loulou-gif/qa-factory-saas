# -*- coding: utf-8 -*-
"""Reporte dans le JSON les modifications faites dans l'Excel ou le Word, puis régénère toutes les vues.

Usage : python outils/synchroniser_vues.py <projet> [--source json|xlsx|docx] [--simulation]

Fonctionne dans 02-a-valider uniquement (ce qui est validé ne se modifie pas).

Repère tout seul le fichier modifié depuis la dernière génération (comparaison du contenu,
pas de la date) :
- aucun : régénère simplement les vues si le JSON a changé ;
- un seul (Excel, Word ou JSON) : il fait foi ; ses modifications sont reportées dans le
  JSON (version + 1) et les autres fichiers sont régénérés ;
- plusieurs, avec des modifications différentes : conflit ; rien n'est écrit, la liste des
  modifications de chaque fichier est affichée, et il faut relancer avec --source pour
  choisir celui qui fait foi (les modifications des autres sont alors perdues).

Code de sortie : 0 succès, 1 erreur, 2 conflit.
"""
import argparse
import json
import subprocess
import sys

import vues_cas
from qa_commun import RACINE, charger_cas, charger_projet, empreinte, erreur, journaliser
from rendre_revue import rendre

VUES = {"xlsx": ("cas-de-tests.xlsx", vues_cas.lire_xlsx), "docx": ("cas-de-tests.docx", vues_cas.lire_docx)}
NOMS = {"json": "cas-de-tests.json", "xlsx": "cas-de-tests.xlsx (Excel)", "docx": "cas-de-tests.docx (Word)"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("projet")
    p.add_argument("--source", choices=["json", "xlsx", "docx"], help="fichier qui fait foi en cas de conflit")
    p.add_argument("--simulation", action="store_true", help="afficher ce qui serait importé, sans rien écrire")
    a = p.parse_args()

    d, projet = charger_projet(a.projet)
    base = d / "02-a-valider"
    fjson = base / "cas-de-tests.json"
    if not fjson.exists():
        if (d / "03-valide" / "cas-de-tests.json").exists():
            erreur("les fichiers sont dans 03-valide (validés) : pour les modifier, le responsable du projet les remet "
                   "d'abord dans 02-a-valider")
        erreur(f"{fjson} introuvable : lancer d'abord /analyser {a.projet}")
    data = charger_cas(fjson)
    proj_json = vues_cas.projection(data)

    etat_f = base / ".synchro.json"
    if etat_f.exists():
        etat = json.loads(etat_f.read_text(encoding="utf-8"))
        snap, emp = etat["projection"], etat.get("empreinte_json")
    else:
        snap, emp = proj_json, None  # première synchronisation : le JSON fait foi

    projs = {"json": proj_json}
    for cle, (nom, lire) in VUES.items():
        f = base / nom
        if f.exists():
            try:
                projs[cle] = lire(f)
            except ImportError:
                erreur("bibliothèque manquante : pip install openpyxl python-docx")
            except PermissionError:
                erreur(f"{f} est ouvert : le fermer puis relancer")
            except Exception as e:
                if a.source and a.source != cle:
                    print(f"{nom} illisible ({e}) : ignoré, il sera régénéré depuis {NOMS[a.source]}")
                    continue
                erreur(f"{nom} illisible : {e}")

    modifies = [k for k, v in projs.items() if v != snap]

    if a.source:
        if a.source not in projs:
            erreur(f"{NOMS[a.source]} absent")
        gagnant = a.source
    elif not modifies:
        gagnant = None
    elif len(modifies) == 1 or all(projs[k] == projs[modifies[0]] for k in modifies):
        gagnant = modifies[0]
    else:
        print("CONFLIT : plusieurs fichiers ont été modifiés différemment depuis la dernière génération.\n")
        for k in modifies:
            print(f"{NOMS[k]} :")
            for ligne in vues_cas.differences(snap, projs[k]):
                print(f"  - {ligne}")
            print()
        print("Rien n'a été écrit. Choisir le fichier qui fait foi (les modifications des autres seront perdues), "
              "ou reporter à la main les modifications de l'un dans l'autre, puis relancer :")
        print(f"  python outils/synchroniser_vues.py {a.projet} --source " + "|".join(modifies))
        sys.exit(2)

    if gagnant is None:
        if emp == empreinte(fjson) and all((base / n).exists() for n, _ in VUES.values()):
            print("Aucune modification à importer : JSON, Excel et Word sont déjà synchronisés.")
            return
        print("Aucune modification à importer dans le JSON ; vues régénérées.")
        if not a.simulation:
            rendre(a.projet, "02-a-valider", forcer=True)
        return

    changes = vues_cas.differences(snap, projs[gagnant])
    print(f"Fichier modifié retenu : {NOMS[gagnant]}")
    for ligne in changes or ["(modifications de forme uniquement)"]:
        print(f"  - {ligne}")
    if a.simulation:
        print("\nSimulation : rien n'a été écrit.")
        return

    if gagnant != "json":
        avant_ct = {c["id"] for c in proj_json["cas"]}
        avant_ex = {e["id"] for e in proj_json["exigences"]}
        data = vues_cas.appliquer(data, json.loads(json.dumps(projs[gagnant])))
        suppr = (avant_ct - {c["id"] for c in data["cas_de_tests"]}) | (avant_ex - {e["id"] for e in data["exigences"]})
        if suppr:
            for t in data.get("strategie_tests") or []:
                for champ in ("cas", "exigences"):
                    if any(x in suppr for x in t.get(champ) or []):
                        t[champ] = [x for x in t[champ] if x not in suppr]
                        print(f"  - {', '.join(sorted(suppr))} retiré(s) de la stratégie ({t['id']})")
            for c in data["cas_de_tests"]:
                if any(x in suppr for x in c.get("exigences") or []):
                    print(f"  - ATTENTION : {c['id']} cite encore {', '.join(x for x in c['exigences'] if x in suppr)} (supprimée)")
            print(f"  - Éléments supprimés : {', '.join(sorted(suppr))}. Vérifier qu'ils ne sont plus cités dans "
                  "jeux-de-donnees.md (Cas concernés) ni dans ambiguites.md (Impact) : le contrôle ci-dessous les signale.")
        fjson.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON mis à jour (version {data['meta']['version']}).")
    rendre(a.projet, "02-a-valider", forcer=True)
    autres = [NOMS[k] for k in ("json", "xlsx", "docx") if k != gagnant]
    print(f"Régénérés depuis {NOMS[gagnant]} : {', '.join(autres)}, cas-de-tests.md.")
    journaliser(d, "synchroniser", f"modifications importées depuis {NOMS[gagnant]} : {len(changes)} changement(s)",
                ["02-a-valider/cas-de-tests.json", "02-a-valider/cas-de-tests.xlsx", "02-a-valider/cas-de-tests.docx"])

    print("\nContrôle :")
    r = subprocess.run([sys.executable, str(RACINE / "outils" / "controle.py"), a.projet], capture_output=True, text=True,
                       encoding="utf-8")
    print(r.stdout.rstrip())
    sys.exit(1 if r.returncode else 0)


if __name__ == "__main__":
    main()
