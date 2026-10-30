# -*- coding: utf-8 -*-
"""Contrôle les fichiers d'analyse d'un projet et écrit la matrice de traçabilité.

Usage : python outils/controle.py <projet> [--dossier 02-a-valider|03-valide]

Code de sortie : 0 si aucune erreur (avertissements possibles), 1 sinon.
Règles : docs/FORMAT-CAS-DE-TESTS.md, section 5, et docs/TECHNIQUES-ISTQB.md.
"""
import argparse
import re
import sys

from qa_commun import (APPROCHES, CRITICITES, DECISIONS, IMPORTANCES, NIVEAUX, RE_CT, RE_EX, RE_JDD, RE_Q, RE_TT, TECHNIQUES,
                       TYPES_CAS, TYPES_CHANGEMENT, TYPES_TEST, charger_cas, charger_projet, empreinte, fonctionnalites, lire_jeux, lire_questions)

VAGUE = re.compile(r"\b(correctement|fonctionne|bien passé|avec succès|comme prévu|sans erreur|normalement|ok)\b", re.I)
VALIDATION = re.compile(r"\b(obligatoire|unique|format|invalide|maximum|minimum|au moins|au plus|caract[eè]res?|longueur|interdit|refus)\b", re.I)


def controler(data, questions, jeux, md_fichier, empreinte_json):
    E, A = [], []
    if not isinstance(data, dict):
        return ["Le JSON ne contient pas un objet."], A
    meta = data.get("meta") or {}
    for champ in ("projet", "sources", "version"):
        if not meta.get(champ):
            E.append(f"meta.{champ} manquant")
    exigences = data.get("exigences")
    cas = data.get("cas_de_tests")
    if not isinstance(exigences, list) or not isinstance(cas, list):
        return E + ["« exigences » et « cas_de_tests » doivent être des tableaux"], A

    ids_ex = {}
    for i, e in enumerate(exigences):
        ou = f"exigences[{i}] ({e.get('id', '?')})"
        if not RE_EX.match(str(e.get("id", ""))):
            E.append(f"{ou} : id au format EX-001 attendu")
        elif e["id"] in ids_ex:
            E.append(f"{ou} : id en double")
        else:
            ids_ex[e["id"]] = e
        for champ in ("titre", "fonctionnalite", "description", "source"):
            if not str(e.get(champ) or "").strip():
                E.append(f"{ou} : « {champ} » manquant")
        if e.get("criticite") and e["criticite"] not in CRITICITES:
            E.append(f"{ou} : criticite « {e['criticite']} » invalide")
        for q in e.get("questions", []):
            if q not in questions:
                E.append(f"{ou} : question {q} absente de ambiguites.md")

    ids_ct, couverture = {}, {x: [] for x in ids_ex}
    jdd_utilises = set()
    for i, c in enumerate(cas):
        ou = f"cas_de_tests[{i}] ({c.get('id', '?')})"
        if not RE_CT.match(str(c.get("id", ""))):
            E.append(f"{ou} : id au format CT0001 attendu")
        elif c["id"] in ids_ct:
            E.append(f"{ou} : id en double")
        else:
            ids_ct[c["id"]] = c
        for champ in ("titre", "fonctionnalite", "prerequis"):
            if not str(c.get(champ) or "").strip():
                E.append(f"{ou} : « {champ} » manquant")
        if c.get("type") not in TYPES_CAS:
            E.append(f"{ou} : type « {c.get('type')} » invalide ({', '.join(sorted(TYPES_CAS))})")
        if c.get("technique") not in TECHNIQUES:
            E.append(f"{ou} : technique « {c.get('technique')} » hors référentiel ISTQB ({', '.join(sorted(TECHNIQUES))})")
        elif c.get("type") == "limite" and c["technique"] != "valeurs-limites":
            A.append(f"{ou} : cas « limite » conçu avec « {c['technique']} » : l'analyse des valeurs limites est attendue")
        elif c["technique"] == "valeurs-limites" and c.get("type") == "nominal" and not c.get("description"):
            A.append(f"{ou} : valeurs limites sans description : préciser la borne testée et sa source")
        tt = c.get("type_test")
        if tt not in TYPES_TEST:
            E.append(f"{ou} : type_test « {tt} » invalide ({', '.join(sorted(TYPES_TEST))})")
        elif c.get("nature") != TYPES_TEST[tt][1]:
            E.append(f"{ou} : nature « {c.get('nature')} » incohérente avec type_test « {tt} » (attendu {TYPES_TEST[tt][1]})")
        if c.get("importance") and c["importance"] not in IMPORTANCES:
            E.append(f"{ou} : importance « {c['importance']} » invalide")
        refs = c.get("exigences") or []
        if not refs:
            E.append(f"{ou} : aucune exigence couverte")
        for r in refs:
            if r not in ids_ex:
                E.append(f"{ou} : exigence {r} inconnue")
            else:
                couverture[r].append(c)
                if ids_ex[r].get("fonctionnalite") != c.get("fonctionnalite"):
                    A.append(f"{ou} : fonctionnalité « {c.get('fonctionnalite')} » différente de celle de {r}")
        etapes = c.get("etapes") or []
        if not etapes:
            E.append(f"{ou} : aucune étape")
        for j, s in enumerate(etapes, start=1):
            if not str(s.get("action") or "").strip():
                E.append(f"{ou} étape {j} : action manquante")
            res = str(s.get("resultat_attendu") or "")
            if not res.strip():
                E.append(f"{ou} étape {j} : résultat attendu manquant")
            elif VAGUE.search(res):
                A.append(f"{ou} étape {j} : résultat attendu vague (« {VAGUE.search(res).group(0)} ») : préciser le fait observable")
        for jdd in c.get("jeux_de_donnees", []):
            if not RE_JDD.match(jdd):
                E.append(f"{ou} : jeu de données « {jdd} » au format JDD-001 attendu")
            elif jdd not in jeux:
                E.append(f"{ou} : {jdd} absent de jeux-de-donnees.md")
            jdd_utilises.add(jdd)
        for q in c.get("questions", []):
            if not RE_Q.match(q) or q not in questions:
                E.append(f"{ou} : question {q} absente de ambiguites.md")
            elif questions[q]["statut"] == "ouverte" and questions[q]["gravite"] == "bloquante":
                A.append(f"{ou} : suspendu à la question bloquante ouverte {q}")

    controler_strategie(data, ids_ex, ids_ct, questions, E, A)

    for ex, lst in couverture.items():
        if not lst:
            A.append(f"{ex} : couverte par aucun cas de test")
        elif VALIDATION.search(ids_ex[ex].get("description", "")) and not any(c.get("type") in ("negatif", "limite") for c in lst):
            A.append(f"{ex} : porte une règle de validation mais n'a aucun cas négatif ou limite")
    for jid, j in jeux.items():
        if jid not in jdd_utilises:
            A.append(f"{jid} : jeu de données utilisé par aucun cas")
        for ct in j["cas"]:
            if ct not in ids_ct:
                E.append(f"{jid} : cas {ct} cité mais absent du JSON")
    for qid, q in questions.items():
        if not q["gravite"] in ("bloquante", "importante", "mineure"):
            E.append(f"{qid} : gravité « {q['gravite']} » invalide (bloquante, importante, mineure)")
        if q["statut"] not in ("ouverte", "répondue", "repondue", "close"):
            E.append(f"{qid} : statut « {q['statut']} » invalide (ouverte, répondue, close)")
        if q["statut"] in ("répondue", "repondue", "close") and not q["reponse"]:
            A.append(f"{qid} : marquée {q['statut']} sans réponse renseignée")
        for ref in q["impact"]:
            if ref not in ids_ex and ref not in ids_ct:
                A.append(f"{qid} : impact {ref} introuvable dans le JSON")

    if not md_fichier.exists():
        E.append("cas-de-tests.md absent : lancer outils/rendre_revue.py")
    else:
        m = re.search(r"empreinte: ([0-9a-f]+)", md_fichier.read_text(encoding="utf-8").split("\n", 1)[0])
        if not m:
            E.append("cas-de-tests.md sans empreinte : il a été modifié à la main, le régénérer avec outils/rendre_revue.py")
        elif m.group(1) != empreinte_json:
            E.append("cas-de-tests.md désynchronisé du JSON : le régénérer avec outils/rendre_revue.py")
    return E, A, couverture


def controler_strategie(data, ids_ex, ids_ct, questions, E, A):
    """Stratégie de types de tests : chaque type ISTQB doit être examiné (retenu, non retenu ou à confirmer)."""
    strat = data.get("strategie_tests")
    if not isinstance(strat, list) or not strat:
        E.append("strategie_tests manquante : chaque type de test ISTQB doit être examiné (docs/TECHNIQUES-ISTQB.md §3)")
        return
    vus, ids = {}, set()
    tous = set(TYPES_TEST) | set(TYPES_CHANGEMENT)
    for i, t in enumerate(strat):
        ou = f"strategie_tests[{i}] ({t.get('id', '?')})"
        if not RE_TT.match(str(t.get("id", ""))):
            E.append(f"{ou} : id au format TT-01 attendu")
        elif t["id"] in ids:
            E.append(f"{ou} : id en double")
        ids.add(t.get("id"))
        tt = t.get("type_test")
        if tt not in tous:
            E.append(f"{ou} : type_test « {tt} » invalide ({', '.join(sorted(tous))})")
            continue
        vus.setdefault(tt, []).append(t)
        if t.get("decision") not in DECISIONS:
            E.append(f"{ou} : decision « {t.get('decision')} » invalide ({', '.join(sorted(DECISIONS))})")
        if not str(t.get("justification") or "").strip():
            E.append(f"{ou} : justification manquante (source du CDC ou raison de l'exclusion)")
        if t.get("decision") == "retenu":
            for champ in ("objectif", "niveau", "approche"):
                if not str(t.get(champ) or "").strip():
                    E.append(f"{ou} : « {champ} » manquant pour un type retenu")
            if t.get("niveau") and t["niveau"] not in NIVEAUX:
                E.append(f"{ou} : niveau « {t['niveau']} » invalide ({', '.join(sorted(NIVEAUX))})")
            if t.get("approche") and t["approche"] not in APPROCHES:
                E.append(f"{ou} : approche « {t['approche']} » invalide ({', '.join(sorted(APPROCHES))})")
            if t.get("approche") == "cas" and not t.get("cas") and tt in TYPES_TEST:
                A.append(f"{ou} : approche « cas » sans cas de test cité")
            if tt in TYPES_TEST and tt != "fonctionnel" and t.get("approche") == "campagne-dediee" and not t.get("questions"):
                A.append(f"{ou} : campagne dédiée sans question liée (seuils, environnement, outillage à confirmer ?)")
        if t.get("decision") == "a-confirmer" and not t.get("questions"):
            E.append(f"{ou} : type « à confirmer » sans question dans ambiguites.md")
        for r in t.get("exigences", []):
            if r not in ids_ex:
                E.append(f"{ou} : exigence {r} inconnue")
        for r in t.get("cas", []):
            if r not in ids_ct:
                E.append(f"{ou} : cas {r} inconnu")
            elif tt in TYPES_TEST and ids_ct[r].get("type_test") != tt:
                A.append(f"{ou} : {r} a le type_test « {ids_ct[r].get('type_test')} »")
        for q in t.get("questions", []):
            if q not in questions:
                E.append(f"{ou} : question {q} absente de ambiguites.md")
    for tt in sorted(tous - set(vus)):
        E.append(f"strategie_tests : type « {tt} » non examiné (le déclarer retenu, non-retenu ou a-confirmer, avec justification)")
    # Les exigences non fonctionnelles et les cas non fonctionnels doivent figurer dans la stratégie.
    cat_type = {"CAT_PERFORMANCE": "performance", "CAT_SECURITY": "securite", "CAT_ERGONOMIC": "utilisabilite"}
    for ex, e in ids_ex.items():
        tt = cat_type.get(e.get("categorie"))
        if tt and not any(ex in t.get("exigences", []) and t.get("decision") != "non-retenu" for t in vus.get(tt, [])):
            A.append(f"{ex} ({e.get('categorie')}) : absente des types « {tt} » retenus ou à confirmer de la stratégie")
    for ct, c in ids_ct.items():
        tt = c.get("type_test")
        if tt in TYPES_TEST and tt != "fonctionnel" and not any(ct in t.get("cas", []) for t in vus.get(tt, [])):
            A.append(f"{ct} : cas de type « {tt} » non rattaché à la stratégie")


def controler_vues(base, data, projet, dossier, E, A):
    """L'Excel et le Word doivent refléter le JSON : sinon des modifications n'ont pas été importées."""
    try:
        import vues_cas
        proj = vues_cas.projection(data)
        lecteurs = (("cas-de-tests.xlsx", vues_cas.lire_xlsx), ("cas-de-tests.docx", vues_cas.lire_docx))
        for nom, lire in lecteurs:
            f = base / nom
            if not f.exists():
                A.append(f"{nom} absent : python outils/rendre_revue.py {projet}" +
                         (" --dossier 03-valide" if dossier == "03-valide" else ""))
                continue
            try:
                ecart = lire(f) != proj
            except ImportError:
                raise
            except Exception as e:
                E.append(f"{nom} illisible : {e}")
                continue
            if ecart and dossier == "03-valide":
                E.append(f"{nom} a été modifié après validation : le responsable du projet remet les fichiers dans "
                         f"02-a-valider, puis /corriger {projet}")
            elif ecart:
                E.append(f"{nom} contient des modifications non reportées dans le JSON : /corriger {projet} "
                         f"(ou python outils/synchroniser_vues.py {projet})")
    except ImportError:
        A.append("python-docx ou openpyxl absent : vues Excel/Word non contrôlées (pip install openpyxl python-docx)")


def ecrire_matrice(base, data, couverture, questions):
    lignes = ["# Matrice de traçabilité exigences → cas de tests", "",
              "Générée par `outils/controle.py`. Ne pas modifier.", "",
              "| Fonctionnalité | Exigence | Criticité | Cas nominaux | Cas négatifs / limites | Types de test | Techniques ISTQB | Questions ouvertes |",
              "|---|---|---|---|---|---|---|---|"]
    for e in data.get("exigences", []):
        lst = couverture.get(e["id"], [])
        nom = [c["id"] for c in lst if c.get("type") == "nominal"]
        autres = [f"{c['id']} ({c.get('type')})" for c in lst if c.get("type") != "nominal"]
        qs = [q for q in e.get("questions", []) if questions.get(q, {}).get("statut") == "ouverte"]
        types = sorted({c.get("type_test", "?") for c in lst})
        techs = sorted({c.get("technique", "?") for c in lst})
        lignes.append(f"| {e.get('fonctionnalite')} | {e['id']} {e.get('titre', '')} | {e.get('criticite', 'MAJOR')} | "
                      f"{', '.join(nom) or '**aucun**'} | {', '.join(autres) or '—'} | {', '.join(types) or '—'} | "
                      f"{', '.join(techs) or '—'} | {', '.join(qs) or '—'} |")
    (base / "matrice-tracabilite.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("projet")
    p.add_argument("--dossier", default="02-a-valider", choices=["02-a-valider", "03-valide"])
    a = p.parse_args()
    d, projet = charger_projet(a.projet)
    base = d / a.dossier
    fjson = base / "cas-de-tests.json"
    data = charger_cas(fjson)
    questions = lire_questions(base / "ambiguites.md")
    jeux = lire_jeux(base / "jeux-de-donnees.md")
    if not (base / "ambiguites.md").exists():
        print("AVERTISSEMENT : ambiguites.md absent")
    if not (base / "jeux-de-donnees.md").exists():
        print("AVERTISSEMENT : jeux-de-donnees.md absent")

    res = controler(data, questions, jeux, base / "cas-de-tests.md", empreinte(fjson))
    E, A = res[0], res[1]
    if isinstance(data, dict):
        controler_vues(base, data, a.projet, a.dossier, E, A)
    couverture = res[2] if len(res) > 2 else {}
    if couverture:
        ecrire_matrice(base, data, couverture, questions)

    cas = data.get("cas_de_tests", []) if isinstance(data, dict) else []
    print(f"Contrôle de {base}")
    print(f"  {len(fonctionnalites(data)) if isinstance(data, dict) else 0} fonctionnalités, "
          f"{len(data.get('exigences', [])) if isinstance(data, dict) else 0} exigences, {len(cas)} cas, "
          f"{len(questions)} questions ({sum(1 for q in questions.values() if q['statut'] == 'ouverte')} ouvertes), "
          f"{len(jeux)} jeux de données")
    for e in E:
        print(f"  ERREUR : {e}")
    for w in A:
        print(f"  AVERTISSEMENT : {w}")
    print(f"Bilan : {len(E)} erreur(s), {len(A)} avertissement(s)" + (" — matrice-tracabilite.md écrite" if couverture else ""))
    sys.exit(1 if E else 0)


if __name__ == "__main__":
    main()
