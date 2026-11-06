# -*- coding: utf-8 -*-
"""Campagnes d'exécution des cas validés sur l'application (temps B), sans IA.

L'agent exécute les cas dans un navigateur et écrit, pour chaque cas, un petit fichier JSON
dans <campagne>/resultats/<CT>.json (format : skill execution-tests). Tout le reste se fait ici,
de façon reproductible :

    python outils/execution.py preparer <projet> --url <lien> [--compte "Rôle"]... [--actions lecture-seule|donnees-de-test]
    python outils/execution.py consolider <projet> [--campagne <AAAAMMJJ-HHMMSS>]
    python outils/execution.py appliquer <projet> --campagne <id> --cas CT0001,CT0004 --par "<nom>"

- preparer : crée 04-livrables/execution/<id>/ avec campagne.json (cas à exécuter, comptes, consignes) ;
- consolider : contrôle les fichiers de l'agent, calcule les statistiques et la couverture des
  exigences, écrit synthese.json, rapport.html, rapport.xlsx et modifications.json ;
- appliquer : reporte dans 03-valide les modifications de cas acceptées par le testeur (version + 1,
  vues régénérées, contrôle ; tout est annulé si le contrôle échoue).
"""
import argparse
import base64
import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from qa_commun import RACINE, RE_CT, charger_projet, fonctionnalites, journaliser

STATUTS = {"reussi": "Réussi", "echoue": "Échoué", "bloque": "Bloqué", "non_execute": "Non exécuté"}
GRAVITES = {"bloquante": "Bloquante", "majeure": "Majeure", "mineure": "Mineure"}
ACTIONS = {"lecture-seule": "Lecture seule : aucune création, modification ni suppression de données",
           "donnees-de-test": "Création de données de test autorisée (jamais de suppression ni de paiement réel)"}
LIBELLES_EXIGENCE = {"validee": "Validée", "echec": "En échec", "partielle": "Partielle", "non_couverte": "Non vérifiée"}
MAX_TEXTE = 2000
MAX_CAPTURE_INTEGREE = 1_500_000  # octets ; au-delà, la capture est citée mais pas intégrée au rapport


class ErreurExecution(Exception):
    pass


def dossier_execution(d: Path) -> Path:
    return d / "04-livrables" / "execution"


def campagnes(d: Path) -> list:
    base = dossier_execution(d)
    if not base.exists():
        return []
    return sorted((p.name for p in base.iterdir() if (p / "campagne.json").exists()), reverse=True)


def dossier_campagne(d: Path, ident: str = "") -> Path:
    ident = ident or (campagnes(d) or [""])[0]
    if not ident or not ident.replace("-", "").isdigit():
        raise ErreurExecution("Aucune campagne d'exécution pour ce projet.")
    c = dossier_execution(d) / ident
    if not (c / "campagne.json").exists():
        raise ErreurExecution(f"Campagne {ident} introuvable.")
    return c


def _texte(v, n=MAX_TEXTE) -> str:
    return " ".join(str(v or "").split())[:n] if not isinstance(v, (dict, list)) else ""


def _texte_long(v, n=MAX_TEXTE) -> str:
    return str(v or "").strip()[:n] if not isinstance(v, (dict, list)) else ""


# ---------------------------------------------------------------- préparation

def preparer(projet: str, url: str, comptes=(), actions: str = "lecture-seule", modele: str = "", par: str = "",
             navigateur: str = "") -> Path:
    d, _ = charger_projet(projet)
    f = d / "03-valide" / "cas-de-tests.json"
    if not f.exists():
        raise ErreurExecution("Les cas doivent être validés avant d'être exécutés (03-valide est vide).")
    if actions not in ACTIONS:
        raise ErreurExecution("Actions autorisées inconnues.")
    data = json.loads(f.read_text(encoding="utf-8"))
    ident = datetime.now().strftime("%Y%m%d-%H%M%S")
    c = dossier_execution(d) / ident
    n = 1
    while c.exists():
        c = dossier_execution(d) / f"{ident[:-2]}{int(ident[-2:]) + n:02d}"
        n += 1
    (c / "resultats").mkdir(parents=True)
    (c / "captures").mkdir()
    campagne = {
        "id": c.name, "debut": datetime.now().isoformat(timespec="seconds"), "url": url, "actions": actions,
        "actions_libelle": ACTIONS[actions], "modele": modele, "par": par, "navigateur": navigateur,
        "version_cas": (data.get("meta") or {}).get("version"),
        "comptes": [{"numero": i, "libelle": str(lib)[:80],
                     "secret_identifiant": f"COMPTE_{i}_IDENTIFIANT", "secret_mot_de_passe": f"COMPTE_{i}_MOT_DE_PASSE"}
                    for i, lib in enumerate(comptes, start=1)],
        "cas": [c_["id"] for c_ in data.get("cas_de_tests") or []],
    }
    (c / "campagne.json").write_text(json.dumps(campagne, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return c


# ---------------------------------------------------------------- consolidation

def _lire_resultat(fichier: Path, cas: dict, campagne_dir: Path, avertissements: list):
    try:
        r = json.loads(fichier.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        avertissements.append(f"{fichier.name} : JSON illisible, ignoré.")
        return None
    if not isinstance(r, dict):
        avertissements.append(f"{fichier.name} : format inattendu, ignoré.")
        return None
    ident = str(r.get("id") or fichier.stem)
    if not RE_CT.match(ident) or ident not in cas:
        avertissements.append(f"{fichier.name} : cas « {ident} » inconnu, ignoré.")
        return None
    statut = str(r.get("statut") or "").strip().lower()
    if statut not in STATUTS:
        avertissements.append(f"{ident} : statut « {statut} » inconnu, compté non exécuté.")
        statut = "non_execute"
    preuves = []
    for p in r.get("preuves") or []:
        chemin = (campagne_dir / str(p)).resolve()
        if campagne_dir.resolve() in chemin.parents and chemin.is_file() and chemin.suffix.lower() in (".png", ".jpg", ".jpeg"):
            preuves.append(chemin.relative_to(campagne_dir.resolve()).as_posix())
        else:
            avertissements.append(f"{ident} : preuve « {p} » introuvable dans la campagne.")
    etapes = []
    for i, e in enumerate(r.get("etapes") or [], start=1):
        if isinstance(e, dict):
            st = str(e.get("statut") or "").lower()
            etapes.append({"numero": int(e.get("numero") or i) if str(e.get("numero") or i).isdigit() else i,
                           "statut": st if st in STATUTS else "non_execute", "observe": _texte(e.get("observe"), 600)})
    anomalie = None
    a = r.get("anomalie")
    if isinstance(a, dict) and _texte(a.get("titre")):
        g = str(a.get("gravite") or "majeure").lower()
        anomalie = {"titre": _texte(a.get("titre"), 200), "gravite": g if g in GRAVITES else "majeure",
                    "description": _texte_long(a.get("description")), "attendu": _texte(a.get("attendu"), 600),
                    "obtenu": _texte(a.get("obtenu"), 600)}
    if statut == "echoue" and not anomalie:
        anomalie = {"titre": _texte(r.get("commentaire"), 200) or "Résultat différent de l'attendu", "gravite": "majeure",
                    "description": "", "attendu": "", "obtenu": ""}
    proposition = None
    p = r.get("proposition")
    if isinstance(p, dict):
        proposition = _proposition(p, cas[ident], ident, avertissements)
    duree = r.get("duree_s")
    return {"id": ident, "statut": statut, "commentaire": _texte_long(r.get("commentaire"), 1000), "etapes": etapes,
            "anomalie": anomalie, "preuves": preuves, "proposition": proposition,
            "duree_s": int(duree) if isinstance(duree, (int, float)) and 0 <= duree < 86400 else None}


def _proposition(p: dict, cas: dict, ident: str, avertissements: list):
    """Modification proposée : seuls titre, prérequis et étapes peuvent changer, avec une raison."""
    apres = {}
    for champ in ("titre", "prerequis"):
        if champ in p:
            v = _texte_long(p.get(champ))
            if v:
                apres[champ] = v
    if "etapes" in p:
        etapes = []
        for e in p.get("etapes") or []:
            if not isinstance(e, dict):
                continue
            a, r = _texte_long(e.get("action")), _texte_long(e.get("resultat_attendu"))
            if a and r:
                etapes.append({"action": a, "resultat_attendu": r})
            elif a or r:
                avertissements.append(f"{ident} : étape proposée incomplète (action et résultat attendu requis), proposition ignorée.")
                return None
        if etapes:
            apres["etapes"] = etapes
    apres = {k: v for k, v in apres.items() if v != cas.get(k)}
    if not apres:
        return None
    raison = _texte_long(p.get("raison"), 1000)
    if not raison:
        avertissements.append(f"{ident} : proposition sans raison, ignorée.")
        return None
    return {"raison": raison, "apres": apres, "avant": {k: cas.get(k) for k in apres}}


def statistiques(data: dict, resultats: dict) -> dict:
    cas = data.get("cas_de_tests") or []
    total = len(cas)
    compte = {s: 0 for s in STATUTS}
    for c in cas:
        compte[(resultats.get(c["id"]) or {}).get("statut", "non_execute")] += 1
    executes = compte["reussi"] + compte["echoue"]
    par_fonction = []
    for f in fonctionnalites(data):
        liste = [c for c in cas if c.get("fonctionnalite") == f]
        if not liste:
            continue
        st = {s: sum(1 for c in liste if (resultats.get(c["id"]) or {}).get("statut", "non_execute") == s) for s in STATUTS}
        par_fonction.append({"nom": f, "total": len(liste), **st})
    exigences = []
    for e in data.get("exigences") or []:
        lies = [c for c in cas if e["id"] in (c.get("exigences") or [])]
        st = [(resultats.get(c["id"]) or {}).get("statut", "non_execute") for c in lies]
        if "echoue" in st:
            etat = "echec"
        elif lies and all(s == "reussi" for s in st):
            etat = "validee"
        elif "reussi" in st:
            etat = "partielle"
        else:
            etat = "non_couverte"
        exigences.append({"id": e["id"], "titre": e.get("titre", ""), "criticite": e.get("criticite", ""),
                          "fonctionnalite": e.get("fonctionnalite", ""), "cas": [c["id"] for c in lies], "etat": etat})
    ex_total = len(exigences)
    ex = {k: sum(1 for e in exigences if e["etat"] == k) for k in LIBELLES_EXIGENCE}
    anomalies = sorted(
        [{"cas": i, "titre_cas": next((c["titre"] for c in cas if c["id"] == i), ""), **r["anomalie"], "preuves": r["preuves"]}
         for i, r in resultats.items() if r["statut"] == "echoue" and r.get("anomalie")],
        key=lambda a: (list(GRAVITES).index(a["gravite"]), a["cas"]))
    durees = [r["duree_s"] for r in resultats.values() if r.get("duree_s")]
    return {
        "cas": {"total": total, **compte, "executes": executes,
                "taux_reussite": round(100 * compte["reussi"] / executes) if executes else None,
                "taux_execution": round(100 * executes / total) if total else 0},
        "exigences": {"total": ex_total, **ex,
                      "couverture": round(100 * (ex_total - ex["non_couverte"]) / ex_total) if ex_total else 0},
        "par_fonctionnalite": par_fonction,
        "detail_exigences": exigences,
        "anomalies": anomalies,
        "duree_totale_s": sum(durees) if durees else None,
    }


def consolider(projet: str, ident: str = "") -> dict:
    d, fiche = charger_projet(projet)
    c = dossier_campagne(d, ident)
    campagne = json.loads((c / "campagne.json").read_text(encoding="utf-8"))
    data = json.loads((d / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
    par_id = {x["id"]: x for x in data.get("cas_de_tests") or []}
    avertissements, resultats = [], {}
    for f in sorted((c / "resultats").glob("*.json")):
        r = _lire_resultat(f, par_id, c, avertissements)
        if r:
            resultats[r["id"]] = r
    stats = statistiques(data, resultats)
    modifications = [{"id": i, "titre_cas": par_id[i]["titre"], "fonctionnalite": par_id[i].get("fonctionnalite", ""),
                      "statut_execution": r["statut"], "preuves": r["preuves"], **r["proposition"], "decision": None}
                     for i, r in sorted(resultats.items()) if r.get("proposition")]
    synthese = {"campagne": campagne, "projet": {"code": projet, "nom": fiche.get("nom", projet)},
                "fin": datetime.now().isoformat(timespec="seconds"), "statistiques": stats,
                "resultats": [resultats.get(x["id"]) or {"id": x["id"], "statut": "non_execute", "commentaire": "Pas de résultat de l'agent.",
                                                         "etapes": [], "anomalie": None, "preuves": [], "duree_s": None}
                              for x in data.get("cas_de_tests") or []],
                "modifications": len(modifications), "avertissements": avertissements}
    (c / "synthese.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ancien = c / "modifications.json"
    if not ancien.exists() or not any(m.get("decision") for m in json.loads(ancien.read_text(encoding="utf-8"))):
        ancien.write_text(json.dumps(modifications, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (c / "rapport.html").write_text(rapport_html(synthese, data, c), encoding="utf-8")
    rapport_excel(synthese, data, c / "rapport.xlsx")
    s = stats["cas"]
    journaliser(d, "executer", f"campagne {c.name} : {s['reussi']} réussi(s), {s['echoue']} échoué(s), {s['bloque']} bloqué(s), "
                f"{s['non_execute']} non exécuté(s) ; {len(modifications)} modification(s) de cas proposée(s)",
                [f"04-livrables/execution/{c.name}/rapport.html"])
    return synthese


# ---------------------------------------------------------------- rapports

def _duree(s):
    if not s:
        return "—"
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s:02d} s" if m else f"{s} s")


def _image(c: Path, rel: str) -> str:
    f = c / rel
    if f.stat().st_size > MAX_CAPTURE_INTEGREE:
        return f'<p class="petit">Capture : {html.escape(rel)} (trop lourde pour être intégrée)</p>'
    mime = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
    return f'<img alt="Capture {html.escape(rel)}" src="data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}">'


def rapport_html(s: dict, data: dict, c: Path) -> str:
    """Rapport autonome (un seul fichier), court : chiffres clés, couverture, anomalies, puis le détail replié."""
    e = html.escape
    st, ex, camp = s["statistiques"]["cas"], s["statistiques"]["exigences"], s["campagne"]
    titres = {x["id"]: x for x in data.get("cas_de_tests") or []}
    taux = f"{st['taux_reussite']} %" if st["taux_reussite"] is not None else "—"

    def barre(n, total, classe):
        return f'<span class="seg {classe}" style="flex:{n}" title="{n}"></span>' if n else ""

    lignes_fonctions = "".join(
        f"<tr><td>{e(f['nom'])}</td><td class='n'>{f['total']}</td><td class='n ok'>{f['reussi']}</td>"
        f"<td class='n ko'>{f['echoue']}</td><td class='n bl'>{f['bloque']}</td><td class='n ne'>{f['non_execute']}</td></tr>"
        for f in s["statistiques"]["par_fonctionnalite"])
    anomalies = "".join(
        f"<article class='anomalie'><h3><span class='grav {a['gravite']}'>{GRAVITES[a['gravite']]}</span> {e(a['cas'])} · {e(a['titre'])}</h3>"
        f"<p class='petit'>Cas : {e(a['titre_cas'])}</p>"
        + (f"<p><strong>Attendu :</strong> {e(a['attendu'])}<br><strong>Obtenu :</strong> {e(a['obtenu'])}</p>" if a['attendu'] or a['obtenu'] else "")
        + (f"<p>{e(a['description'])}</p>" if a['description'] else "")
        + "".join(_image(c, p) for p in a["preuves"][:2]) + "</article>"
        for a in s["statistiques"]["anomalies"]) or "<p>Aucune anomalie constatée.</p>"
    exigences_a_voir = [x for x in s["statistiques"]["detail_exigences"] if x["etat"] != "validee"]
    lignes_exigences = "".join(
        f"<tr><td>{e(x['id'])}</td><td>{e(x['titre'])}</td><td>{e(x['criticite'])}</td>"
        f"<td><span class='etat {x['etat']}'>{LIBELLES_EXIGENCE[x['etat']]}</span></td><td>{e(', '.join(x['cas']) or '—')}</td></tr>"
        for x in exigences_a_voir)
    detail = "".join(
        f"<tr><td>{e(r['id'])}</td><td>{e(titres.get(r['id'], {}).get('titre', ''))}</td>"
        f"<td><span class='etat {r['statut']}'>{STATUTS[r['statut']]}</span></td><td>{e(r.get('commentaire') or '')}</td></tr>"
        for r in s["resultats"])
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport de tests · {e(s['projet']['nom'])}</title>
<style>
:root {{ --violet:#675AA2; --violet-fonce:#4A3F82; --encre:#262338; --gris:#6E6A80; --trait:#E4E2EE; --fond:#F7F7FB;
  --ok:#2F8F6B; --ko:#C0392B; --bl:#B7791F; --ne:#A9A6B8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--encre); background:var(--fond); }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:1.6rem; margin:0 0 .25rem; }} h2 {{ font-size:1.15rem; margin:2rem 0 .75rem; }} h3 {{ font-size:1rem; margin:0 0 .4rem; }}
.petit {{ color:var(--gris); font-size:.88rem; }}
.chiffres {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:1.25rem; }}
.chiffre {{ background:#fff; border:1px solid var(--trait); border-radius:12px; padding:14px 16px; }}
.chiffre b {{ display:block; font-size:1.7rem; line-height:1.2; font-variant-numeric:tabular-nums; }}
.chiffre span {{ color:var(--gris); font-size:.88rem; }}
.repartition {{ display:flex; height:12px; border-radius:999px; overflow:hidden; background:var(--trait); margin:16px 0 6px; }}
.seg.ok {{ background:var(--ok); }} .seg.ko {{ background:var(--ko); }} .seg.bl {{ background:var(--bl); }} .seg.ne {{ background:var(--ne); }}
.legende {{ display:flex; flex-wrap:wrap; gap:14px; font-size:.86rem; color:var(--gris); }}
.legende i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--trait); border-radius:12px; overflow:hidden; font-size:.92rem; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--trait); vertical-align:top; }}
th {{ background:var(--fond); font-weight:650; }} th.n, td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.ok {{ color:var(--ok); }} td.ko {{ color:var(--ko); }} td.bl {{ color:var(--bl); }} td.ne {{ color:var(--gris); }}
.etat {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:.82rem; font-weight:650; white-space:nowrap; background:var(--fond); }}
.etat.reussi, .etat.validee {{ color:var(--ok); background:#E6F4EE; }} .etat.echoue, .etat.echec {{ color:var(--ko); background:#FBEAE8; }}
.etat.bloque, .etat.partielle {{ color:var(--bl); background:#FBF2E2; }}
.anomalie {{ background:#fff; border:1px solid var(--trait); border-left:4px solid var(--ko); border-radius:10px; padding:14px 16px; margin-bottom:12px; }}
.anomalie img {{ max-width:100%; border:1px solid var(--trait); border-radius:8px; margin-top:8px; }}
.grav {{ font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.03em; color:var(--ko); margin-right:4px; }}
.grav.mineure {{ color:var(--bl); }}
details {{ margin-top:2rem; }} summary {{ cursor:pointer; font-weight:650; color:var(--violet-fonce); }}
.tableau {{ overflow-x:auto; }}
@media print {{ body {{ background:#fff; }} details {{ display:block; }} details > * {{ display:block; }} }}
</style></head><body><main>
<h1>Rapport de tests · {e(s['projet']['nom'])}</h1>
<p class="petit">Campagne du {e(camp['debut'][:16].replace('T', ' à '))} sur {e(camp['url'])} · version {e(str(camp.get('version_cas') or '—'))} des cas
 · durée {_duree(s['statistiques']['duree_totale_s'])}{(' · modèle ' + e(camp['modele'])) if camp.get('modele') else ''}</p>

<div class="chiffres">
  <div class="chiffre"><b>{st['executes']}/{st['total']}</b><span>cas exécutés</span></div>
  <div class="chiffre"><b>{taux}</b><span>de réussite</span></div>
  <div class="chiffre"><b>{len(s['statistiques']['anomalies'])}</b><span>anomalie{'s' if len(s['statistiques']['anomalies']) > 1 else ''}</span></div>
  <div class="chiffre"><b>{ex['couverture']} %</b><span>des exigences vérifiées ({ex['validee']} validée{'s' if ex['validee'] > 1 else ''} sur {ex['total']})</span></div>
</div>
<div class="repartition" role="img" aria-label="{st['reussi']} réussis, {st['echoue']} échoués, {st['bloque']} bloqués, {st['non_execute']} non exécutés">
{barre(st['reussi'], st['total'], 'ok')}{barre(st['echoue'], st['total'], 'ko')}{barre(st['bloque'], st['total'], 'bl')}{barre(st['non_execute'], st['total'], 'ne')}</div>
<div class="legende"><span><i style="background:var(--ok)"></i>{st['reussi']} réussi{'s' if st['reussi'] > 1 else ''}</span>
<span><i style="background:var(--ko)"></i>{st['echoue']} échoué{'s' if st['echoue'] > 1 else ''}</span>
<span><i style="background:var(--bl)"></i>{st['bloque']} bloqué{'s' if st['bloque'] > 1 else ''}</span>
<span><i style="background:var(--ne)"></i>{st['non_execute']} non exécuté{'s' if st['non_execute'] > 1 else ''}</span></div>

<h2>Anomalies</h2>
{anomalies}

<h2>Par fonctionnalité</h2>
<div class="tableau"><table><thead><tr><th>Fonctionnalité</th><th class="n">Cas</th><th class="n">Réussis</th><th class="n">Échoués</th><th class="n">Bloqués</th><th class="n">Non exécutés</th></tr></thead>
<tbody>{lignes_fonctions}</tbody></table></div>

{f'''<h2>Exigences à surveiller</h2><p class="petit">Les {ex['validee']} autres exigences sont validées : tous leurs cas ont réussi.</p>
<div class="tableau"><table><thead><tr><th>Exigence</th><th>Titre</th><th>Criticité</th><th>État</th><th>Cas</th></tr></thead><tbody>{lignes_exigences}</tbody></table></div>''' if exigences_a_voir else '<h2>Exigences</h2><p>Toutes les exigences sont validées.</p>'}

<details><summary>Détail des {st['total']} cas</summary>
<div class="tableau" style="margin-top:12px"><table><thead><tr><th>Cas</th><th>Titre</th><th>Résultat</th><th>Commentaire</th></tr></thead><tbody>{detail}</tbody></table></div>
</details>
<p class="petit" style="margin-top:2rem">Produit par QA Factory. Actions autorisées pendant les tests : {e(camp.get('actions_libelle', ''))}.</p>
</main></body></html>
"""


def rapport_excel(s: dict, data: dict, chemin: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    entete = Font(bold=True, color="FFFFFF")
    fond = PatternFill("solid", fgColor="675AA2")
    couleurs = {"reussi": "E6F4EE", "validee": "E6F4EE", "echoue": "FBEAE8", "echec": "FBEAE8", "bloque": "FBF2E2", "partielle": "FBF2E2"}

    def feuille(ws, titres, lignes, largeurs, colonne_etat=None):
        ws.append(titres)
        for cel in ws[1]:
            cel.font, cel.fill = entete, fond
        for l in lignes:
            ws.append(l)
        for i, w in enumerate(largeurs, start=1):
            ws.column_dimensions[chr(64 + i)].width = w
        for row in ws.iter_rows(min_row=2):
            for cel in row:
                cel.alignment = Alignment(wrap_text=True, vertical="top")
            if colonne_etat is not None:
                cle = row[colonne_etat].value
                code = next((k for k, v in {**STATUTS, **LIBELLES_EXIGENCE}.items() if v == cle), None)
                if code in couleurs:
                    row[colonne_etat].fill = PatternFill("solid", fgColor=couleurs[code])
        ws.freeze_panes = "A2"

    st, ex, camp = s["statistiques"]["cas"], s["statistiques"]["exigences"], s["campagne"]
    ws = wb.active
    ws.title = "Synthèse"
    feuille(ws, ["Indicateur", "Valeur"], [
        ["Projet", s["projet"]["nom"]], ["Application", camp["url"]], ["Début", camp["debut"].replace("T", " ")],
        ["Version des cas", camp.get("version_cas")], ["Cas", st["total"]], ["Exécutés", st["executes"]],
        ["Réussis", st["reussi"]], ["Échoués", st["echoue"]], ["Bloqués", st["bloque"]], ["Non exécutés", st["non_execute"]],
        ["Taux de réussite (%)", st["taux_reussite"]], ["Exigences", ex["total"]], ["Exigences validées", ex["validee"]],
        ["Exigences en échec", ex["echec"]], ["Couverture des exigences (%)", ex["couverture"]],
        ["Anomalies", len(s["statistiques"]["anomalies"])], ["Actions autorisées", camp.get("actions_libelle", "")]], [32, 60])
    titres = {x["id"]: x for x in data.get("cas_de_tests") or []}
    feuille(wb.create_sheet("Cas"), ["Cas", "Titre", "Fonctionnalité", "Importance", "Résultat", "Commentaire", "Anomalie", "Gravité"],
            [[r["id"], titres.get(r["id"], {}).get("titre", ""), titres.get(r["id"], {}).get("fonctionnalite", ""),
              titres.get(r["id"], {}).get("importance", ""), STATUTS[r["statut"]], r.get("commentaire") or "",
              (r.get("anomalie") or {}).get("titre", ""), GRAVITES.get((r.get("anomalie") or {}).get("gravite"), "")]
             for r in s["resultats"]], [10, 45, 22, 12, 14, 50, 40, 12], colonne_etat=4)
    feuille(wb.create_sheet("Exigences"), ["Exigence", "Titre", "Fonctionnalité", "Criticité", "État", "Cas liés"],
            [[x["id"], x["titre"], x["fonctionnalite"], x["criticite"], LIBELLES_EXIGENCE[x["etat"]], ", ".join(x["cas"])]
             for x in s["statistiques"]["detail_exigences"]], [10, 50, 22, 12, 14, 30], colonne_etat=4)
    feuille(wb.create_sheet("Anomalies"), ["Cas", "Gravité", "Titre", "Attendu", "Obtenu", "Description", "Preuves"],
            [[a["cas"], GRAVITES[a["gravite"]], a["titre"], a["attendu"], a["obtenu"], a["description"], ", ".join(a["preuves"])]
             for a in s["statistiques"]["anomalies"]], [10, 12, 40, 40, 40, 50, 30])
    wb.save(chemin)


# ---------------------------------------------------------------- modifications acceptées

def appliquer(projet: str, ident: str, acceptes: list, par: str) -> int:
    """Reporte dans 03-valide les modifications acceptées ; les autres sont marquées refusées."""
    d, _ = charger_projet(projet)
    c = dossier_campagne(d, ident)
    fm = c / "modifications.json"
    mods = json.loads(fm.read_text(encoding="utf-8")) if fm.exists() else []
    if any(m.get("decision") for m in mods):
        raise ErreurExecution("Les modifications de cette campagne ont déjà été traitées.")
    inconnus = set(acceptes) - {m["id"] for m in mods}
    if inconnus:
        raise ErreurExecution("Cas sans modification proposée : " + ", ".join(sorted(inconnus)))
    f = d / "03-valide" / "cas-de-tests.json"
    if (d / "02-a-valider" / "cas-de-tests.json").exists():
        raise ErreurExecution("Des cas sont en relecture : terminez la relecture avant d'appliquer ces modifications.")
    data = json.loads(f.read_text(encoding="utf-8"))
    par_id = {x["id"]: x for x in data.get("cas_de_tests") or []}
    n = 0
    for m in mods:
        if m["id"] not in acceptes:
            continue
        cas = par_id.get(m["id"])
        if not cas:
            raise ErreurExecution(f"{m['id']} n'existe plus dans les cas validés.")
        for champ, avant in (m.get("avant") or {}).items():
            if cas.get(champ) != avant:
                raise ErreurExecution(f"{m['id']} a été modifié depuis la campagne : relancez les tests avant d'appliquer.")
        cas.update(m["apres"])
        n += 1
    if n:
        sauvegarde = {p.name: p.read_bytes() for p in (d / "03-valide").iterdir() if p.is_file()}
        data.setdefault("meta", {})["version"] = int(data["meta"].get("version") or 0) + 1
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outils = RACINE / "outils"
        r = subprocess.run([sys.executable, str(outils / "rendre_revue.py"), projet, "--dossier", "03-valide", "--forcer"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RACINE)
        k = subprocess.run([sys.executable, str(outils / "controle.py"), projet, "--dossier", "03-valide"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=RACINE)
        if r.returncode or k.returncode:
            for nom, contenu in sauvegarde.items():
                (d / "03-valide" / nom).write_bytes(contenu)
            erreurs = [l.split("ERREUR : ", 1)[1] for l in (k.stdout + r.stderr).splitlines() if "ERREUR : " in l]
            raise ErreurExecution("Les modifications rendent les cas invalides ; rien n'a été changé. " + " ; ".join(erreurs[:5]))
    for m in mods:
        m["decision"] = "acceptee" if m["id"] in acceptes else "refusee"
        m["decide_par"], m["decide_le"] = par, datetime.now().isoformat(timespec="seconds")
    fm.write_text(json.dumps(mods, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    journaliser(d, "executer-modifications", f"campagne {c.name} : {n} cas mis à jour par {par}, "
                f"{len(mods) - n} proposition(s) refusée(s)", ["03-valide/cas-de-tests.json"] if n else [])
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)
    a = sp.add_parser("preparer")
    a.add_argument("projet")
    a.add_argument("--url", required=True)
    a.add_argument("--compte", action="append", default=[])
    a.add_argument("--actions", default="lecture-seule", choices=list(ACTIONS))
    a = sp.add_parser("consolider")
    a.add_argument("projet")
    a.add_argument("--campagne", default="")
    a = sp.add_parser("appliquer")
    a.add_argument("projet")
    a.add_argument("--campagne", required=True)
    a.add_argument("--cas", default="")
    a.add_argument("--par", default="")
    x = p.parse_args()
    try:
        if x.action == "preparer":
            print(preparer(x.projet, x.url, x.compte, x.actions))
        elif x.action == "consolider":
            s = consolider(x.projet, x.campagne)["statistiques"]["cas"]
            print(f"{s['reussi']} réussi(s), {s['echoue']} échoué(s), {s['bloque']} bloqué(s), {s['non_execute']} non exécuté(s)")
        else:
            print(f"{appliquer(x.projet, x.campagne, [i for i in x.cas.split(',') if i], x.par)} cas mis à jour")
    except ErreurExecution as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
