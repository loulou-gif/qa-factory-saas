# -*- coding: utf-8 -*-
"""Application web QA Factory SaaS (FastAPI, pages rendues côté serveur).

Parcours (skill interface-qa-factory) : déposer -> génération -> fichiers produits -> relecture
et enregistrement (= validation) -> envoi dans Squash.

Lancement : uvicorn app.main:app --app-dir saas --host 0.0.0.0 --port 8000
"""
import json
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import campagnes, connexions, parametres, projets, relais_ia
from .config import ICI, reglages
from .db import STATUTS_ACTIFS, Base, maintenant
from .moteur import ErreurMoteur, moteur
from .securite import ROLES, controler_csrf, hacher, jeton_csrf, mot_de_passe_valable, verifier
from .taches import STATUTS as STATUTS_TACHES, TYPES as TYPES_TACHES, ErreurTache, gestionnaire, progression

reglages.preparer()
import vues_cas  # noqa: E402  (outils/ est ajouté au chemin par reglages.preparer)
from qa_commun import fonctionnalites as fonctionnalites_cas  # noqa: E402

base = Base(reglages.base)


class Redirection(Exception):
    def __init__(self, url):
        self.url = url


def creer_admin_initial():
    if base.un("SELECT id FROM utilisateurs LIMIT 1"):
        return
    ident, mdp = os.environ.get("QAF_ADMIN_IDENTIFIANT"), os.environ.get("QAF_ADMIN_MOT_DE_PASSE")
    if ident and mdp:
        base.x("INSERT INTO utilisateurs (identifiant, nom, role, mot_de_passe, doit_changer, cree_le) VALUES (?,?,?,?,1,?)",
               (ident.strip().lower(), os.environ.get("QAF_ADMIN_NOM", "Administrateur"), "admin", hacher(mdp), maintenant()))


@asynccontextmanager
async def cycle(app_):
    creer_admin_initial()
    gestionnaire.demarrer(base)
    yield


app = FastAPI(title="QA Factory", lifespan=cycle, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=reglages.secret, session_cookie="qaf_session", max_age=12 * 3600,
                   same_site="strict", https_only=reglages.cookie_securise)
app.mount("/statique", StaticFiles(directory=str(ICI / "statique")), name="statique")
gabarits = Jinja2Templates(directory=str(ICI / "gabarits"))
gabarits.env.globals.update(ROLES=ROLES, lib=vues_cas)


@app.exception_handler(Redirection)
async def _redirection(request, exc):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(HTTPException)
async def _erreur_http(request, exc):
    if request.headers.get("accept", "").startswith("application/json") or request.url.path.startswith(("/taches/", "/demarrer")):
        return JSONResponse({"erreur": exc.detail}, status_code=exc.status_code)
    return gabarits.TemplateResponse(request, "erreur.html", {"u": utilisateur(request, obligatoire=False), "message": exc.detail,
                                                               "csrf": jeton_csrf(request)}, status_code=exc.status_code)


# ---------------------------------------------------------------- outils de page

def utilisateur(request: Request, obligatoire=True):
    uid = request.session.get("uid")
    u = base.un("SELECT * FROM utilisateurs WHERE id = ? AND actif = 1", (uid,)) if uid else None
    if not u and obligatoire:
        if request.url.path.startswith(("/taches/", "/demarrer")) or request.method == "POST":
            raise HTTPException(401, "Session expirée : reconnectez-vous.")
        raise Redirection("/connexion")
    if u and obligatoire and u["doit_changer"] and request.url.path not in ("/compte", "/deconnexion"):
        raise Redirection("/compte")
    return u


def flash(request: Request, message: str, genre="info"):
    request.session.setdefault("flash", []).append({"m": message, "g": genre})


def page(request: Request, nom: str, **ctx):
    ctx.setdefault("u", utilisateur(request, obligatoire=False))
    ctx["csrf"] = jeton_csrf(request)
    ctx["flashs"] = request.session.pop("flash", [])
    return gabarits.TemplateResponse(request, nom, ctx)


async def json_controle(request: Request) -> dict:
    """Corps JSON d'un appel fait par la page ; le jeton CSRF voyage dans l'en-tête X-CSRF."""
    controler_csrf(request, request.headers.get("x-csrf", ""))
    try:
        return await request.json()
    except Exception:  # noqa: BLE001
        return {}


def exiger_projet(code):
    if not projets.existe(code):
        raise HTTPException(404, "Projet introuvable.")


def dossier_lecture(code):
    e = projets.etat(code)
    return ("02-a-valider" if e["a_valider"] else "03-valide"), e


def a_envoyer(code, e) -> int:
    """Cas validés, non suspendus à une question bloquante, pas encore dans Squash."""
    if not e["valide"] or e["a_valider"]:
        return 0
    data = projets.charger_cas(code, "03-valide") or {}
    bloques = projets.cas_bloques(code, "03-valide")
    try:
        corr = json.loads((projets.dossier(code) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        corr = {}
    deja = set((corr.get("cas_de_tests") or {}).keys())
    return sum(1 for c in data.get("cas_de_tests", []) if c["id"] not in bloques and c["id"] not in deja)


def resume_tests(code) -> dict:
    """Application testée, comptes et derniers résultats, pour la page du projet."""
    _, s, mods = campagne_lisible(code)
    return {"app_": campagnes.application(code), "nb_comptes": len(campagnes.comptes(base, code)), "derniers": s,
            "mods_en_attente": len(mods) if mods and not any(m.get("decision") for m in mods) else 0}


def resume_automatisation(code, e) -> dict:
    """Scénarios déjà automatisés et dernière génération, pour la page du projet."""
    if not e.get("valide"):
        return {}
    import automatisation as outil
    import execution_scripts
    try:
        r = outil.resume(code)
        r["execution"] = (execution_scripts.resume(code) or {}).get("derniere")
        return r
    except Exception:  # noqa: BLE001
        return {}


def resume_documents_projet(code, e) -> dict:
    """Derniers cahier de tests et manuel produits, pour la page du projet."""
    if not e.get("valide"):
        return {}
    import manuel as outil
    try:
        c, r = cahiers_produits(code), outil.redactions(code)
    except Exception:  # noqa: BLE001
        return {}
    return {"cahier": c[0] if c else None, "manuel": r[0] if r else None}


def connexion_exigee(u):
    """Connexion Squash de l'utilisateur, ou erreur 409 qui l'invite à la régler."""
    cx = connexions.lire(base, u["id"])
    if not cx:
        raise HTTPException(409, "Connectez d'abord votre Squash : Paramètres > Connexion Squash, en bas du menu.")
    return cx


def derniere_tache(code, type_):
    t = base.un("SELECT id FROM taches WHERE projet = ? AND type = ? ORDER BY id DESC LIMIT 1", (code, type_))
    return base.tache(t["id"]) if t else None


# ---------------------------------------------------------------- connexion et compte

@app.get("/sante")
def sante():
    ok, detail = moteur.disponible()
    return JSONResponse({"application": "ok", "moteur": "ok" if ok else detail})


@app.get("/connexion", response_class=HTMLResponse)
def connexion_page(request: Request):
    return page(request, "connexion.html", u=None)


@app.post("/connexion")
def connexion(request: Request, identifiant: str = Form(...), mot_de_passe: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = base.un("SELECT * FROM utilisateurs WHERE identifiant = ? AND actif = 1", (identifiant.strip().lower(),))
    if not u or not verifier(mot_de_passe, u["mot_de_passe"]):
        flash(request, "Identifiant ou mot de passe incorrect.", "erreur")
        return RedirectResponse("/connexion", status_code=303)
    request.session.clear()
    request.session["uid"] = u["id"]
    base.auditer(u["id"], None, "connexion")
    return RedirectResponse("/", status_code=303)


@app.post("/deconnexion")
def deconnexion(request: Request, csrf: str = Form("")):
    controler_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/connexion", status_code=303)


@app.get("/compte", response_class=HTMLResponse)
def compte_page(request: Request):
    return page(request, "compte.html", u=utilisateur(request))


@app.post("/compte")
def compte(request: Request, actuel: str = Form(...), nouveau: str = Form(...), confirmation: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    if not verifier(actuel, u["mot_de_passe"]):
        flash(request, "Mot de passe actuel incorrect.", "erreur")
    elif nouveau != confirmation:
        flash(request, "Les deux nouveaux mots de passe ne sont pas identiques.", "erreur")
    elif mot_de_passe_valable(nouveau):
        flash(request, f"Mot de passe trop faible : {mot_de_passe_valable(nouveau)}.", "erreur")
    elif nouveau == actuel:
        flash(request, "Le nouveau mot de passe doit être différent de l'actuel.", "erreur")
    else:
        base.x("UPDATE utilisateurs SET mot_de_passe = ?, doit_changer = 0 WHERE id = ?", (hacher(nouveau), u["id"]))
        base.auditer(u["id"], None, "changement-mot-de-passe")
        flash(request, "Mot de passe changé.", "ok")
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/compte", status_code=303)


# ---------------------------------------------------------------- accueil : déposer, c'est lancer

def resume_projet(code):
    f, e = projets.fiche(code), projets.etat(code)
    active = gestionnaire.active(code)
    if active and active["type"] in ("analyser", "corriger"):
        statut = ("encours", "Génération en cours")
    elif e["a_valider"]:
        statut = ("relire", "À relire")
    elif e["valide"] and not e["publie"]:
        statut = ("valide", "Validé")
    elif e["publie"]:
        statut = ("squash", "Dans Squash")
    else:
        statut = ("vide", "Analyse à relancer")
    d = projets.dossier(code)
    return {"code": code, "nom": f.get("nom", code), "statut": statut, "e": e,
            "modifie": max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=0)}


def liste_projets():
    res = []
    for code in projets.lister():
        try:
            res.append(resume_projet(code))
        except Exception:  # noqa: BLE001
            continue
    return sorted(res, key=lambda p: p["modifie"], reverse=True)


@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    u = utilisateur(request)
    ok, detail = moteur.disponible()
    return page(request, "accueil.html", u=u, recents=liste_projets()[:4], moteur_ok=ok, moteur_detail=detail,
                extensions=",".join(sorted(e.lstrip(".") for e in projets.EXTENSIONS_DOCUMENTS)))


@app.post("/demarrer")
async def demarrer(request: Request, fichiers: List[UploadFile] = File(...)):
    """Dépôt des fichiers : crée le projet, y range les documents et lance l'analyse."""
    controler_csrf(request, request.headers.get("x-csrf", ""))
    u = utilisateur(request)
    fichiers = [f for f in fichiers if f.filename]
    if not fichiers:
        raise HTTPException(400, "Aucun fichier reçu.")
    for f in fichiers:
        if os.path.splitext(f.filename)[1].lower() not in projets.EXTENSIONS_DOCUMENTS:
            raise HTTPException(400, f"{f.filename} : format non accepté. Formats acceptés : "
                                     f"{', '.join(sorted(projets.EXTENSIONS_DOCUMENTS))}.")
    documents = [(f.filename, await f.read()) for f in fichiers]
    textes, insuffisant = projets.evaluer_documents(documents)
    if insuffisant:
        raise HTTPException(422, insuffisant)
    ok, detail = moteur.disponible()
    if not ok:
        raise HTTPException(503, f"L'assistant d'analyse est indisponible ({detail}). Prévenez l'administrateur.")
    principal = max(fichiers, key=lambda f: (f.filename.lower().endswith((".pdf", ".docx", ".doc", ".odt", ".md")), f.size or 0))
    code, nom = projets.code_depuis_nom(principal.filename), projets.nom_depuis_fichier(principal.filename)
    try:
        projets.creer(code, nom, "", None, u["nom"])
        for nom_fichier, donnees in documents:
            projets.deposer_document(code, nom_fichier, donnees)
        projets.enregistrer_textes(code, textes)
    except projets.ErreurProjet as e:
        projets.supprimer_projet_vide(code)
        raise HTTPException(400, str(e))
    base.x("INSERT OR REPLACE INTO projets (code, responsable_id, cree_par, cree_le) VALUES (?,?,?,?)",
           (code, u["id"], u["id"], maintenant()))
    base.auditer(u["id"], code, "depot-et-analyse", ", ".join(f.filename for f in fichiers))
    try:
        tid = gestionnaire.soumettre(code, "analyser", u)
    except ErreurTache as e:
        raise HTTPException(409, str(e))
    return {"tache": tid, "projet": code, "nom": nom}


# ---------------------------------------------------------------- suivi des tâches (appelé par la page)

@app.get("/taches/{tid}/progression")
def tache_progression(request: Request, tid: int):
    utilisateur(request)
    t = base.tache(tid)
    if not t:
        raise HTTPException(404, "Tâche introuvable.")
    p = progression(t)
    r = t["resultat"] or {}
    reponse = {"statut": t["statut"], "actif": t["statut"] in STATUTS_ACTIFS, "type": t["type"], "projet": t["projet"],
               "pourcentage": p["pourcentage"], "message": p["message"], "attente": t["attente"] or [],
               "erreur": p["message"] if t["statut"] in ("echec", "interrompue", "annule") else ""}
    if t["type"] == "publier-simulation" and t["statut"] == "termine":
        reponse["simulation"] = {"projet": r.get("projet"), "resume": r.get("resume"), "jeux": r.get("jeux") or {},
                                 "exclus": len(r.get("exclus") or {}), "details": r.get("details") or [],
                                 "avertissements": r.get("avertissements") or [],
                                 "dossier_racine": next((x["id"] for x in r.get("plan") or []
                                                         if x.get("racine") and x.get("action") == "creer"), "")}
    if t["type"] == "publier" and t["statut"] == "termine":
        reponse["crees"] = len(r.get("crees") or [])
        reponse["modifies"] = len(r.get("modifies") or [])
        reponse["non_mis_a_jour"] = r.get("non_mis_a_jour") or []
    if t["type"] == "tester":
        reponse["campagne"] = (t["parametres"] or {}).get("campagne")
    if t["type"] == "automatiser":
        reponse["generation"] = (t["parametres"] or {}).get("generation")
    if t["type"] == "executer-scripts":
        reponse["execution"] = (t["parametres"] or {}).get("execution")
    return reponse


@app.post("/taches/{tid}/permission")
async def tache_permission(request: Request, tid: int):
    corps = await json_controle(request)
    u = utilisateur(request)
    t = base.tache(tid)
    demande, accepter = corps.get("demande", ""), bool(corps.get("accepter"))
    a = next((x for x in (t["attente"] or []) if x.get("id") == demande), None) if t else None
    if not a:
        return {"ok": True}
    try:
        moteur.repondre_permission(demande, accepter, "" if accepter else f"Refusé par {u['nom']}")
    except ErreurMoteur as e:
        raise HTTPException(502, str(e))
    base.ajouter_journal(tid, f"{'Autorisé' if accepter else 'Refusé'} par {u['nom']} : {a.get('permission')} {a.get('detail', '')}")
    base.auditer(u["id"], t["projet"], f"permission:{'accepter' if accepter else 'refuser'}", a.get("detail", ""))
    base.maj_tache(tid, attente=[x for x in t["attente"] if x["id"] != demande] or None)
    return {"ok": True}


@app.post("/taches/{tid}/question")
async def tache_question(request: Request, tid: int):
    corps = await json_controle(request)
    u = utilisateur(request)
    t = base.tache(tid)
    demande = corps.get("demande", "")
    q = next((x for x in (t["attente"] or []) if x.get("id") == demande and x["genre"] == "question"), None) if t else None
    if not q:
        return {"ok": True}
    try:
        if corps.get("ignorer"):
            moteur.rejeter_question(demande)
        else:
            moteur.repondre_question(demande, [[str(x) for x in r] for r in corps.get("reponses") or []])
    except ErreurMoteur as e:
        raise HTTPException(502, str(e))
    base.ajouter_journal(tid, f"Question {'écartée' if corps.get('ignorer') else 'répondue'} par {u['nom']}.")
    base.maj_tache(tid, attente=[x for x in t["attente"] if x["id"] != demande] or None)
    return {"ok": True}


@app.post("/taches/{tid}/arreter")
async def tache_arreter(request: Request, tid: int):
    await json_controle(request)
    gestionnaire.annuler(tid, utilisateur(request))
    return {"ok": True}


# ---------------------------------------------------------------- projets

@app.get("/projets", response_class=HTMLResponse)
def projets_page(request: Request):
    return page(request, "projets.html", u=utilisateur(request), liste=liste_projets())


@app.get("/projets/{code}", response_class=HTMLResponse)
def fichiers_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    p = resume_projet(code)
    nom_dossier, e = dossier_lecture(code)
    analyse = e["a_valider"] or e["valide"]
    data = projets.charger_cas(code, nom_dossier) if analyse else None
    qs = projets.questions(code, nom_dossier) if analyse else []
    active = gestionnaire.active(code)
    return page(request, "fichiers.html", u=u, p=p, code=code, fiche=projets.fiche(code), e=e, dossier=nom_dossier, data=data,
                fonctions=len({c.get("fonctionnalite") for c in (data or {}).get("cas_de_tests", [])}),
                questions=qs, bloquantes=[q for q in qs if q["statut"] == "ouverte" and q["gravite"] == "bloquante"],
                jeux=len(projets.jeux(code, nom_dossier)) if analyse else 0, active=active,
                echec=derniere_tache(code, "analyser") if not analyse and not active else None,
                squash_id=(projets.fiche(code).get("squash") or {}).get("projet_id"),
                squash_nom=(projets.fiche(code).get("squash") or {}).get("projet_nom") or "",
                url_application=(projets.fiche(code).get("application") or {}).get("url") or "",
                bloques=len(projets.cas_bloques(code, "03-valide")) if e["valide"] and not e["a_valider"] else 0,
                a_envoyer=a_envoyer(code, e),
                a_maj=projets.a_mettre_a_jour(code) if e["valide"] and not e["a_valider"] and e["publie"] else [], squash_cx=connexions.resume(connexions.lire(base, u["id"])),
                automatisation=resume_automatisation(code, e), documents=resume_documents_projet(code, e), **resume_tests(code))


@app.get("/projets/{code}/cas", response_class=HTMLResponse)
def cas_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    nom_dossier, e = dossier_lecture(code)
    data = projets.charger_cas(code, nom_dossier)
    if not data:
        raise HTTPException(404, "Pas encore de cas de tests pour ce projet.")
    from qa_commun import fonctionnalites
    qs = projets.questions(code, nom_dossier)
    bloquantes = {q["id"] for q in qs if q["statut"] == "ouverte" and q["gravite"] == "bloquante"}
    groupes = [(f, [c for c in data["cas_de_tests"] if c.get("fonctionnalite") == f]) for f in fonctionnalites(data)]
    groupes = [(f, l) for f, l in groupes if l]
    return page(request, "cas.html", u=u, code=code, fiche=projets.fiche(code), data=data, groupes=groupes,
                modifiable=nom_dossier == "02-a-valider" and not gestionnaire.active(code),
                bloquantes=bloquantes, nb_bloquantes=len(bloquantes),
                natures=Counter(c.get("type") for c in data["cas_de_tests"]))


@app.post("/projets/{code}/enregistrer")
async def enregistrer(request: Request, code: str):
    """Enregistrer = reporter les modifications, contrôler, puis valider (passage dans 03-valide)."""
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        raise HTTPException(409, "Une tâche est en cours sur ce projet : attendez sa fin.")
    try:
        n = projets.enregistrer_modifications(code, corps.get("modifications") or [])
        c = projets.controle(code)
        if not c["ok"]:
            return JSONResponse({"erreur": "Le contrôle a trouvé des problèmes à corriger avant d'enregistrer.",
                                 "details": c["erreurs"][:8]}, status_code=422)
        projets.valider(code, u["nom"])
        r = projets.script("generer_specs.py", code)
    except projets.ErreurProjet as e:
        raise HTTPException(400, str(e))
    base.auditer(u["id"], code, "enregistrement-validation", f"{n} cas modifié(s)")
    flash(request, "Enregistré et validé." + (f" {n} cas modifié(s)." if n else "")
          + ("" if r.returncode == 0 else " Les specs d'automatisation n'ont pas pu être générées."), "ok")
    return {"ok": True, "redirection": f"/projets/{code}"}


@app.post("/projets/{code}/relancer")
def relancer(request: Request, code: str, csrf: str = Form("")):
    """Relance l'analyse avec les documents déjà déposés (après un échec)."""
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    try:
        gestionnaire.soumettre(code, "analyser", u)
        base.auditer(u["id"], code, "relance-analyse")
    except ErreurTache as e:
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/projets/{code}", status_code=303)


@app.post("/projets/{code}/rouvrir")
def rouvrir(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    try:
        projets.remettre_en_relecture(code, u["nom"])
        base.auditer(u["id"], code, "remise-en-relecture")
        flash(request, "Les cas sont de nouveau modifiables.", "ok")
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/projets/{code}", status_code=303)


@app.get("/projets/{code}/questions", response_class=HTMLResponse)
def questions_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    nom_dossier, e = dossier_lecture(code)
    qs = projets.questions(code, nom_dossier)
    data = projets.charger_cas(code, nom_dossier) or {}
    cas_par_question = {}
    for c in data.get("cas_de_tests", []):
        for q in c.get("questions") or []:
            cas_par_question.setdefault(q, []).append(c["id"])
    repondues = [q for q in qs if q["statut"] in ("répondue", "repondue")]
    return page(request, "questions.html", u=u, code=code, fiche=projets.fiche(code), dossier=nom_dossier, questions=qs,
                cas_par_question=cas_par_question, modifiable=not gestionnaire.active(code),
                peut_integrer=bool(repondues) and nom_dossier == "02-a-valider")


@app.post("/projets/{code}/questions/{qid}")
async def question_repondre(request: Request, code: str, qid: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        raise HTTPException(409, "Une tâche est en cours sur ce projet : attendez sa fin.")
    try:
        statut = projets.repondre_question(code, qid, corps.get("reponse") or "", bool(corps.get("faux_positif")), u["nom"])
    except projets.ErreurProjet as ex:
        raise HTTPException(400, str(ex))
    base.auditer(u["id"], code, "reponse-question", f"{qid} : {statut}")
    nom_dossier, _ = dossier_lecture(code)
    return {"ok": True, "statut": statut, "bloques": len(projets.cas_bloques(code, nom_dossier))}


@app.post("/projets/{code}/questions-integrer")
def questions_integrer(request: Request, code: str, csrf: str = Form("")):
    """Fait intégrer par l'assistant les réponses apportées aux questions dans les cas concernés."""
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    qs = [q for q in projets.questions(code, "02-a-valider") if q["statut"] in ("répondue", "repondue")]
    if not qs:
        flash(request, "Aucune réponse à intégrer.", "erreur")
        return RedirectResponse(f"/projets/{code}/questions", status_code=303)
    demande = ("Intégrer dans les cas de tests concernés les réponses apportées aux questions "
               + ", ".join(q["id"] for q in qs)
               + " (champ Réponse de ambiguites.md). Ne modifier que ce que ces réponses changent ; ne rien inventer.")
    try:
        gestionnaire.soumettre(code, "corriger", u, {"demande": demande})
        base.auditer(u["id"], code, "integration-reponses", ", ".join(q["id"] for q in qs))
    except ErreurTache as ex:
        flash(request, str(ex), "erreur")
    return RedirectResponse(f"/projets/{code}", status_code=303)


@app.get("/projets/{code}/donnees", response_class=HTMLResponse)
def donnees_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    nom_dossier, e = dossier_lecture(code)
    return page(request, "donnees.html", u=u, code=code, fiche=projets.fiche(code), dossier=nom_dossier,
                jeux=projets.jeux(code, nom_dossier), modifiable=not gestionnaire.active(code), publie=bool(e["publie"]))


@app.post("/projets/{code}/donnees")
async def donnees_enregistrer(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        raise HTTPException(409, "Une tâche est en cours sur ce projet : attendez sa fin.")
    try:
        n = projets.enregistrer_jeux(code, corps.get("modifications") or [], u["nom"])
    except projets.ErreurProjet as ex:
        raise HTTPException(400, str(ex))
    base.auditer(u["id"], code, "jeux-de-donnees", f"{n} jeu(x)")
    return {"ok": True, "n": n}


@app.get("/projets/{code}/telecharger/{chemin:path}")
def telecharger(request: Request, code: str, chemin: str):
    u = utilisateur(request)
    exiger_projet(code)
    try:
        f = projets.fichier_telechargeable(code, chemin)
    except projets.ErreurProjet as e:
        raise HTTPException(404, str(e))
    base.auditer(u["id"], code, "telechargement", chemin)
    return FileResponse(f, filename=f.name)


# ---------------------------------------------------------------- Squash

@app.get("/projets/{code}/squash/projets")
def squash_projets(request: Request, code: str):
    """Projets visibles avec la connexion Squash de l'utilisateur, pour les choisir par leur nom."""
    u = utilisateur(request)
    exiger_projet(code)
    cx = connexion_exigee(u)
    try:
        res = connexions.appeler_module(cx, "--lister-projets", timeout=90)
    except connexions.ErreurConnexion as ex:
        raise HTTPException(502, str(ex))
    if res.get("erreurs"):
        raise HTTPException(502, connexions.expliquer(res["erreurs"], connexions.adresse_affichee(cx["url"]), cx["mode"]))
    return {"projets": res.get("projets") or []}


@app.post("/projets/{code}/squash/simuler")
async def squash_simuler(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    cx = connexion_exigee(u)
    sid = str(corps.get("squash_id") or "").strip()
    fiche = projets.fiche(code)
    url = (corps.get("url") or "").strip()
    if url:
        if not re.match(r"^https?://[^\s/]+", url):
            raise HTTPException(400, "Le lien de l'application doit commencer par http:// ou https://.")
        fiche.setdefault("application", {})["url"] = url[:500]
        projets.ecrire_fiche(code, fiche)
    if sid:
        if not sid.isdigit():
            raise HTTPException(400, "Choisissez le projet Squash dans la liste.")
        fiche.setdefault("squash", {})["projet_id"] = int(sid)
        if corps.get("squash_nom"):
            fiche["squash"]["projet_nom"] = str(corps["squash_nom"])[:200]
        projets.ecrire_fiche(code, fiche)
        # Le fichier validé doit viser le même projet Squash.
        f = projets.dossier(code) / "03-valide" / "cas-de-tests.json"
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            if (data.get("projet") or {}).get("id") != int(sid):
                data.setdefault("projet", {})["id"] = int(sid)
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                projets.script("rendre_revue.py", code, "--dossier", "03-valide", "--forcer")
    if not (fiche.get("squash") or {}).get("projet_id"):
        raise HTTPException(400, "Choisissez le projet Squash.")
    try:
        tid = gestionnaire.soumettre(code, "publier-simulation", u, {"instance": cx["url"]})
    except ErreurTache as e:
        raise HTTPException(409, str(e))
    return {"tache": tid}


@app.post("/projets/{code}/squash/publier")
async def squash_publier(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    s = base.tache(int(corps.get("simulation") or 0))
    if not s or s["projet"] != code or s["type"] != "publier-simulation" or s["statut"] != "termine":
        raise HTTPException(400, "La vérification préalable n'est plus valable : recommencez.")
    r = s["resultat"] or {}
    cx = connexion_exigee(u)
    if r.get("instance") != cx["url"]:
        raise HTTPException(409, "La connexion Squash a changé depuis la vérification : recommencez l'envoi.")
    resume = r.get("resume") or {}
    # Conflits à remplacer par la version QA Factory : uniquement des conflits de cette vérification.
    forcer = corps.get("forcer") or []
    conflits = {d["id"] for d in (r.get("details") or []) if d.get("action") == "conflit" and d.get("conflits")}
    if not isinstance(forcer, list) or any(not isinstance(x, str) or x not in conflits for x in forcer):
        raise HTTPException(400, "Choix de remplacement invalide : recommencez la vérification.")
    deja = 0
    try:
        c = json.loads((projets.dossier(code) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
        deja = sum(len(c.get(k) or {}) for k in ("exigences", "cas_de_tests", "dossiers_exigences", "dossiers_cas"))
    except Exception:  # noqa: BLE001
        pass
    try:
        tid = gestionnaire.soumettre(code, "publier", u, {"empreinte": r.get("empreinte"), "simulation": s["id"], "instance": cx["url"],
                                                          "a_creer": int(resume.get("creer", 0)) + int(resume.get("recreer", 0)),
                                                          "a_maj": int(resume.get("modifier", 0)) + len(forcer),
                                                          "forcer": sorted(set(forcer)), "deja": deja})
    except ErreurTache as e:
        raise HTTPException(409, str(e))
    return {"tache": tid}


# ---------------------------------------------------------------- connexion Squash de l'utilisateur

@app.get("/parametres/squash", response_class=HTMLResponse)
def parametres_squash_page(request: Request):
    u = utilisateur(request)
    cx = connexions.resume(connexions.lire(base, u["id"]))
    saisie = request.session.pop("saisie_squash", None) or {}
    return page(request, "parametres_squash.html", u=u, cx=cx, modes=connexions.MODES,
                adresse=saisie.get("adresse", cx["adresse"] if cx else ""),
                mode=saisie.get("mode", cx["mode"] if cx else "jeton"),
                identifiant=saisie.get("identifiant", cx["identifiant"] if cx else ""))


@app.post("/parametres/squash")
def parametres_squash(request: Request, adresse: str = Form(""), mode: str = Form("jeton"), identifiant: str = Form(""),
                      secret: str = Form(""), csrf: str = Form("")):
    """Teste la connexion avec Squash, puis l'enregistre (secret chiffré) si elle fonctionne."""
    controler_csrf(request, csrf)
    u = utilisateur(request)
    try:
        cx = connexions.enregistrer(base, u["id"], adresse, mode, identifiant, secret)
    except connexions.ErreurConnexion as e:
        request.session["saisie_squash"] = {"adresse": adresse[:500], "mode": mode, "identifiant": identifiant[:200]}
        flash(request, f"Connexion non enregistrée. {e}", "erreur")
        return RedirectResponse("/parametres/squash", status_code=303)
    base.auditer(u["id"], None, "connexion-squash", f"{connexions.adresse_affichee(cx['url'])} ({cx['mode']})")
    n = cx["projets_visibles"]
    flash(request, f"Squash est connecté : {n} projet{'s' if n > 1 else ''} visible{'s' if n > 1 else ''} avec ce compte.", "ok")
    return RedirectResponse("/parametres/squash", status_code=303)


@app.post("/parametres/squash/supprimer")
def parametres_squash_supprimer(request: Request, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    connexions.supprimer(base, u["id"])
    base.auditer(u["id"], None, "connexion-squash-supprimee")
    flash(request, "Connexion à Squash supprimée : le mot de passe ou le jeton a été effacé.", "ok")
    return RedirectResponse("/parametres/squash", status_code=303)


# ---------------------------------------------------------------- tests de l'application (temps B)

def campagne_lisible(code, ident=""):
    """(dossier, synthèse, modifications) de la campagne demandée ou de la dernière consolidée."""
    import execution as outil
    d = projets.dossier(code)
    for c in ([ident] if ident else outil.campagnes(d)):
        try:
            dossier = outil.dossier_campagne(d, c)
        except outil.ErreurExecution:
            continue
        if (dossier / "synthese.json").exists():
            mods = dossier / "modifications.json"
            return (dossier, json.loads((dossier / "synthese.json").read_text(encoding="utf-8")),
                    json.loads(mods.read_text(encoding="utf-8")) if mods.exists() else [])
    return None, None, []


@app.get("/projets/{code}/application", response_class=HTMLResponse)
def application_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    saisie = request.session.pop("saisie_application", None) or {}
    app_ = campagnes.application(code)
    return page(request, "application.html", u=u, code=code, fiche=projets.fiche(code), app_=app_, actions=campagnes.ACTIONS,
                url=saisie.get("url", app_["url"]), domaines=saisie.get("domaines", "\n".join(app_["autres_domaines"])),
                comptes=campagnes.comptes(base, code), max_comptes=campagnes.MAX_COMPTES)


@app.post("/projets/{code}/application")
def application_enregistrer(request: Request, code: str, url: str = Form(""), actions: str = Form("lecture-seule"),
                            domaines: str = Form(""), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    try:
        a = campagnes.enregistrer_application(code, url, actions, domaines)
        base.auditer(u["id"], code, "application-testee", f"{a['url']} ({a['actions']})")
        flash(request, "Application enregistrée.", "ok")
    except campagnes.ErreurCampagne as e:
        request.session["saisie_application"] = {"url": url[:500], "domaines": domaines[:1000]}
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/projets/{code}/application", status_code=303)


@app.post("/projets/{code}/application/comptes")
def application_compte(request: Request, code: str, libelle: str = Form(""), identifiant: str = Form(""),
                       mot_de_passe: str = Form(""), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    try:
        campagnes.ajouter_compte(base, code, libelle, identifiant, mot_de_passe, u["id"])
        base.auditer(u["id"], code, "compte-test-ajoute", libelle.strip()[:80])
        flash(request, "Compte de test ajouté. Son mot de passe est chiffré et ne sera plus affiché.", "ok")
    except campagnes.ErreurCampagne as e:
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/projets/{code}/application#comptes", status_code=303)


@app.post("/projets/{code}/application/comptes/{cid}/supprimer")
def application_compte_supprimer(request: Request, code: str, cid: int, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    campagnes.supprimer_compte(base, code, cid)
    base.auditer(u["id"], code, "compte-test-supprime", str(cid))
    flash(request, "Compte de test supprimé.", "ok")
    return RedirectResponse(f"/projets/{code}/application#comptes", status_code=303)


@app.post("/projets/{code}/tester")
async def tester(request: Request, code: str):
    await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["valide"] or e["a_valider"]:
        raise HTTPException(409, "Les cas doivent être validés (et aucune relecture en cours) avant d'être exécutés.")
    if not campagnes.application(code)["url"]:
        raise HTTPException(409, "Indiquez d'abord le lien de l'application à tester.")
    ok, detail = moteur.disponible()
    if not ok:
        raise HTTPException(503, f"L'assistant est indisponible ({detail}). Prévenez l'administrateur.")
    try:
        tid = gestionnaire.soumettre(code, "tester", u)
    except ErreurTache as ex:
        raise HTTPException(409, str(ex))
    return {"tache": tid}


@app.get("/projets/{code}/tests", response_class=HTMLResponse)
def tests_page(request: Request, code: str, campagne: str = ""):
    u = utilisateur(request)
    exiger_projet(code)
    dossier, s, mods = campagne_lisible(code, campagne)
    if not s:
        raise HTTPException(404, "Aucun résultat de tests pour ce projet.")
    data = projets.charger_cas(code, "03-valide") or {}
    import execution as outil
    return page(request, "tests.html", u=u, code=code, fiche=projets.fiche(code), s=s, st=s["statistiques"],
                titres={c["id"]: c for c in data.get("cas_de_tests") or []}, statuts=outil.STATUTS, gravites=outil.GRAVITES,
                etats_exigence=outil.LIBELLES_EXIGENCE, mods=mods, a_decider=bool(mods) and not any(m.get("decision") for m in mods),
                chemin=f"04-livrables/execution/{dossier.name}", campagnes=outil.campagnes(projets.dossier(code)))


@app.get("/projets/{code}/tests/modifications", response_class=HTMLResponse)
def modifications_page(request: Request, code: str, campagne: str = ""):
    u = utilisateur(request)
    exiger_projet(code)
    dossier, s, mods = campagne_lisible(code, campagne)
    if not mods:
        raise HTTPException(404, "Aucune modification de cas proposée.")
    return page(request, "modifications.html", u=u, code=code, fiche=projets.fiche(code), mods=mods, campagne=dossier.name,
                chemin=f"04-livrables/execution/{dossier.name}", traitees=any(m.get("decision") for m in mods),
                occupe=bool(gestionnaire.active(code)))


@app.post("/projets/{code}/tests/modifications")
async def modifications_appliquer(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        raise HTTPException(409, "Une tâche est en cours sur ce projet : attendez sa fin.")
    import execution as outil
    acceptes = [str(i) for i in corps.get("acceptes") or [] if isinstance(i, str)]
    try:
        n = outil.appliquer(code, str(corps.get("campagne") or ""), acceptes, u["nom"])
    except outil.ErreurExecution as ex:
        raise HTTPException(400, str(ex))
    if n:
        projets.script("generer_specs.py", code)
    base.auditer(u["id"], code, "modifications-cas", f"campagne {corps.get('campagne')} : {n} acceptée(s)")
    flash(request, (f"{n} cas mis à jour dans la version validée." if n else "Aucune modification retenue : les cas sont inchangés.")
          + (" Mettez Squash à jour depuis la page du projet." if n and projets.etat(code)["publie"] else ""), "ok")
    return {"ok": True, "redirection": f"/projets/{code}"}


# ---------------------------------------------------------------- automatisation Playwright (temps B, lot 3)

@app.get("/projets/{code}/automatisation", response_class=HTMLResponse)
def automatisation_page(request: Request, code: str, execution: str = ""):
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["valide"] or e["a_valider"]:
        raise HTTPException(409, "Les cas doivent être validés (et aucune relecture en cours) avant d'être automatisés.")
    import automatisation as outil
    try:
        pr = outil.priorites(code)
    except outil.ErreurAutomatisation as ex:
        raise HTTPException(409, str(ex))
    import execution_scripts
    groupes = [(k, lib, [c for c in pr["cas"] if c["niveau"] == k]) for k, lib in outil.NIVEAUX.items()]
    r = outil.resume(code)
    ex = execution_scripts.resume(code)
    if execution:
        try:
            ex["derniere"] = json.loads((execution_scripts.dossier_execution(projets.dossier(code), execution) / "synthese.json")
                                        .read_text(encoding="utf-8"))
        except (execution_scripts.ErreurExecutionScripts, OSError, ValueError):
            raise HTTPException(404, "Exécution introuvable.")
    statuts_ex = ex["statuts"]
    for c in pr["cas"]:
        c["dernier_resultat"] = statuts_ex.get(c["id"], "") if c["script"] else ""
    active = gestionnaire.active(code)
    pw_ok, pw_detail = execution_scripts.disponible()
    return page(request, "automatisation.html", u=u, code=code, fiche=projets.fiche(code), pr=pr, groupes=groupes,
                langages=outil.LANGAGES, derniere=r["derniere"], statuts=outil.STATUTS, app_=campagnes.application(code),
                nb_comptes=len(campagnes.comptes(base, code)), occupe=active,
                chemin_depot=outil.DEPOT, ex=ex, statuts_ex=execution_scripts.STATUTS, playwright_ok=pw_ok, playwright_detail=pw_detail)


@app.post("/projets/{code}/automatiser")
async def automatiser(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["valide"] or e["a_valider"]:
        raise HTTPException(409, "Les cas doivent être validés (et aucune relecture en cours) avant d'être automatisés.")
    if not campagnes.application(code)["url"]:
        raise HTTPException(409, "Indiquez d'abord le lien de l'application à tester.")
    import automatisation as outil
    cas = [str(x) for x in corps.get("cas") or [] if isinstance(x, str)][:60]
    langage = str(corps.get("langage") or "js")
    if not cas:
        raise HTTPException(400, "Cochez au moins un scénario à automatiser.")
    if langage not in outil.LANGAGES:
        raise HTTPException(400, "Langage inconnu.")
    deja = outil.langage_depot(projets.dossier(code))
    if deja and deja != langage:
        raise HTTPException(409, f"Le dépôt d'automatisation est déjà en {outil.LANGAGES[deja]}.")
    connus = {c["id"] for c in (projets.charger_cas(code, "03-valide") or {}).get("cas_de_tests") or []}
    inconnus = [x for x in cas if x not in connus]
    if inconnus:
        raise HTTPException(400, f"Cas inconnu(s) : {', '.join(inconnus[:5])}.")
    ok, detail = moteur.disponible()
    if not ok:
        raise HTTPException(503, f"L'assistant est indisponible ({detail}). Prévenez l'administrateur.")
    try:
        tid = gestionnaire.soumettre(code, "automatiser", u, {"cas": cas, "langage": langage})
    except ErreurTache as ex:
        raise HTTPException(409, str(ex))
    return {"tache": tid, "redirection": f"/projets/{code}"}


# ---------------------------------------------------------------- exécution des scripts (temps B, lot 4)

@app.post("/projets/{code}/executer-scripts")
async def executer_scripts(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    import automatisation as outil
    import execution_scripts
    if not campagnes.application(code)["url"]:
        raise HTTPException(409, "Indiquez d'abord le lien de l'application à tester.")
    existants = outil.scripts_existants(projets.dossier(code))
    if not existants:
        raise HTTPException(409, "Aucun script à exécuter : générez d'abord des scripts.")
    cas = [str(x) for x in corps.get("cas") or [] if isinstance(x, str)][:200]
    inconnus = [x for x in cas if x not in existants]
    if inconnus:
        raise HTTPException(400, f"Aucun script pour : {', '.join(inconnus[:5])}.")
    ok, detail = execution_scripts.disponible()
    if not ok:
        raise HTTPException(503, detail)
    try:
        tid = gestionnaire.soumettre(code, "executer-scripts", u, {"cas": cas})
    except ErreurTache as ex:
        raise HTTPException(409, str(ex))
    return {"tache": tid, "redirection": f"/projets/{code}"}


MEDIAS_RAPPORT = {".html": "text/html; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webm": "video/webm", ".gif": "image/gif"}


@app.get("/projets/{code}/automatisation/executions/{ident}/rapport/{chemin:path}")
def rapport_playwright(request: Request, code: str, ident: str, chemin: str):
    """Rapport HTML de Playwright. Seul index.html (écrit par Playwright) s'affiche comme page ; les pièces jointes
    autres qu'images et vidéos sont téléchargées, dans un bac à sable."""
    utilisateur(request)
    exiger_projet(code)
    import execution_scripts
    try:
        e = execution_scripts.dossier_execution(projets.dossier(code), ident)
    except execution_scripts.ErreurExecutionScripts:
        raise HTTPException(404, "Rapport introuvable.")
    racine = (e / "rapport").resolve()
    f = (racine / (chemin or "index.html")).resolve()
    if racine not in f.parents or not f.is_file():
        raise HTTPException(404, "Rapport introuvable.")
    rel = f.relative_to(racine).as_posix()
    entetes = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "private, max-age=300"}
    media = MEDIAS_RAPPORT.get(f.suffix.lower())
    if rel == "index.html":
        return FileResponse(f, media_type=media, headers=entetes)
    entetes["Content-Security-Policy"] = "sandbox; default-src 'none'"
    if media and f.suffix.lower() != ".html":
        return FileResponse(f, media_type=media, headers=entetes)
    return FileResponse(f, media_type="application/octet-stream", filename=f.name, headers=entetes)


@app.get("/projets/{code}/automatisation/archive")
def archive_scripts(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    import execution_scripts
    try:
        nom, contenu = execution_scripts.archive(code)
    except execution_scripts.ErreurExecutionScripts as ex:
        raise HTTPException(404, str(ex))
    base.auditer(u["id"], code, "telechargement", "archive des scripts")
    return Response(contenu, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{nom}"'})


# ---------------------------------------------------------------- administration

def exiger_admin(request):
    u = utilisateur(request)
    if u["role"] != "admin":
        raise HTTPException(403, "Réservé aux administrateurs.")
    return u


@app.get("/admin/utilisateurs", response_class=HTMLResponse)
def admin_utilisateurs(request: Request):
    u = exiger_admin(request)
    return page(request, "utilisateurs.html", u=u, liste=base.tous("SELECT * FROM utilisateurs ORDER BY actif DESC, nom"))


@app.post("/admin/utilisateurs")
def admin_creer(request: Request, identifiant: str = Form(...), nom: str = Form(...), role: str = Form(...),
                mot_de_passe: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = exiger_admin(request)
    ident = identifiant.strip().lower()
    if role not in ROLES or not ident or not nom.strip():
        flash(request, "Identifiant, nom et rôle obligatoires.", "erreur")
    elif mot_de_passe_valable(mot_de_passe):
        flash(request, f"Mot de passe provisoire trop faible : {mot_de_passe_valable(mot_de_passe)}.", "erreur")
    elif base.un("SELECT id FROM utilisateurs WHERE identifiant = ?", (ident,)):
        flash(request, "Cet identifiant existe déjà.", "erreur")
    else:
        base.x("INSERT INTO utilisateurs (identifiant, nom, role, mot_de_passe, doit_changer, cree_le) VALUES (?,?,?,?,1,?)",
               (ident, nom.strip(), role, hacher(mot_de_passe), maintenant()))
        base.auditer(u["id"], None, "creation-utilisateur", f"{ident} ({role})")
        flash(request, f"Compte {ident} créé. Mot de passe provisoire à changer à la première connexion.", "ok")
    return RedirectResponse("/admin/utilisateurs", status_code=303)


@app.post("/admin/utilisateurs/{uid}")
def admin_modifier(request: Request, uid: int, action: str = Form(...), role: str = Form(""), mot_de_passe: str = Form(""),
                   csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = exiger_admin(request)
    cible = base.un("SELECT * FROM utilisateurs WHERE id = ?", (uid,))
    if not cible:
        raise HTTPException(404, "Compte introuvable.")
    if cible["id"] == u["id"] and action in ("desactiver", "role"):
        flash(request, "Impossible de modifier son propre compte ainsi.", "erreur")
    elif action == "desactiver":
        base.x("UPDATE utilisateurs SET actif = 0 WHERE id = ?", (uid,))
        flash(request, f"Compte {cible['identifiant']} désactivé.", "ok")
    elif action == "activer":
        base.x("UPDATE utilisateurs SET actif = 1 WHERE id = ?", (uid,))
        flash(request, f"Compte {cible['identifiant']} réactivé.", "ok")
    elif action == "role" and role in ROLES:
        base.x("UPDATE utilisateurs SET role = ? WHERE id = ?", (role, uid))
        flash(request, f"Rôle de {cible['identifiant']} : {ROLES[role]}.", "ok")
    elif action == "reinitialiser":
        if mot_de_passe_valable(mot_de_passe):
            flash(request, f"Mot de passe provisoire trop faible : {mot_de_passe_valable(mot_de_passe)}.", "erreur")
        else:
            base.x("UPDATE utilisateurs SET mot_de_passe = ?, doit_changer = 1 WHERE id = ?", (hacher(mot_de_passe), uid))
            flash(request, f"Mot de passe de {cible['identifiant']} réinitialisé (à changer à la prochaine connexion).", "ok")
    base.auditer(u["id"], None, f"utilisateur:{action}", cible["identifiant"])
    return RedirectResponse("/admin/utilisateurs", status_code=303)


# ---------------------------------------------------------------- documents de recette (cahier de tests, manuel)

def exiger_role(request, *roles):
    u = utilisateur(request)
    if u["role"] not in roles:
        raise HTTPException(403, "Réservé aux " + " et aux ".join({"admin": "administrateurs", "responsable": "responsables de projet",
                                                                    "testeur": "testeurs"}[r] for r in roles) + ".")
    return u


def cahiers_produits(code) -> list:
    d = projets.dossier(code) / "04-livrables" / "cahier"
    res = []
    for f in sorted(d.glob("*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True) if d.exists() else []:
        if f.name.startswith(("~$", ".")):
            continue
        from datetime import datetime
        res.append({"nom": f.name, "chemin": f"04-livrables/cahier/{f.name}", "taille": f.stat().st_size,
                    "date": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y à %H:%M")})
    return res


@app.get("/projets/{code}/documents", response_class=HTMLResponse)
def documents_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    import manuel as outil_manuel
    data = projets.charger_cas(code, "03-valide") if e["valide"] else None
    fonctions = fonctionnalites_cas(data) if data else []
    active = gestionnaire.active(code)
    redactions = outil_manuel.redactions(code) if e["valide"] else []
    echec = derniere_tache(code, "manuel")
    if echec and (echec["statut"] != "echec" or (redactions and redactions[0]["redaction"] == (echec["parametres"] or {}).get("redaction"))):
        echec = None
    return page(request, "documents.html", u=u, code=code, fiche=projets.fiche(code), e=e, fonctions=fonctions,
                cas_par_fonction={f: sum(1 for c in data["cas_de_tests"] if c.get("fonctionnalite") == f) for f in fonctions} if data else {},
                nb_nominaux=sum(1 for c in (data or {}).get("cas_de_tests", []) if c.get("type") == "nominal"),
                cahiers=cahiers_produits(code), redactions=redactions[:5], modeles=parametres.resume_documents(base),
                app_=campagnes.application(code), nb_comptes=len(campagnes.comptes(base, code)), active=active,
                echec_manuel=echec, modele_ia=parametres.modele_pour(base, "manuel"),
                peut_modeles=u["role"] in ("admin", "responsable"))


@app.post("/projets/{code}/cahier")
def generer_cahier(request: Request, code: str, nominaux: str = Form(""), csrf: str = Form("")):
    """Cahier de tests depuis les cas validés, au modèle de l'entreprise s'il a été déposé (sans IA, quelques secondes)."""
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["valide"]:
        raise HTTPException(409, "Le cahier se génère depuis les cas validés : enregistrez d'abord la relecture.")
    modele = parametres.chemin_modele("cahier")
    args = [code, "--sans-exploration"] + (["--nominaux"] if nominaux else []) + (["--modele", str(modele)] if modele else [])
    r = projets.script("build_cahier.py", *args, timeout=300)
    if r.returncode:
        detail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["erreur inconnue"]
        flash(request, "Le cahier n'a pas pu être généré : " + detail[0].replace("ERREUR : ", ""), "erreur")
    else:
        base.auditer(u["id"], code, "cahier", "modèle de l'entreprise" if modele else "modèle interne")
        flash(request, "Cahier de tests généré" + (" au modèle de l'entreprise." if modele else " au modèle interne.")
              + (" Parcours nominaux uniquement." if nominaux else ""), "ok")
    return RedirectResponse(f"/projets/{code}/documents#cahier", status_code=303)


@app.post("/projets/{code}/manuel")
async def rediger_manuel(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["valide"]:
        raise HTTPException(409, "Le manuel se rédige à partir des cas validés : enregistrez d'abord la relecture.")
    if not campagnes.application(code)["url"]:
        raise HTTPException(409, "Indiquez d'abord le lien de l'application à décrire.")
    connues = fonctionnalites_cas(projets.charger_cas(code, "03-valide") or {})
    choisies = [f for f in corps.get("fonctionnalites") or [] if isinstance(f, str) and f in connues]
    if not choisies:
        raise HTTPException(400, "Cochez au moins une fonctionnalité à décrire.")
    ok, detail = moteur.disponible()
    if not ok:
        raise HTTPException(503, f"L'assistant est indisponible ({detail}). Prévenez l'administrateur.")
    try:
        tid = gestionnaire.soumettre(code, "manuel", u, {"fonctionnalites": choisies})
    except ErreurTache as ex:
        raise HTTPException(409, str(ex))
    return {"tache": tid, "redirection": f"/projets/{code}/documents"}


@app.post("/projets/{code}/manuel/{ident}/mise-en-page")
def manuel_mise_en_page(request: Request, code: str, ident: str, csrf: str = Form("")):
    """Remet en page une rédaction déjà faite avec le modèle Word actuel (après le dépôt d'un nouveau modèle), sans IA."""
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        raise HTTPException(409, "Une tâche est en cours sur ce projet : attendre sa fin.")
    import manuel as outil
    _, valeurs = campagnes.secrets(base, code)
    try:
        s = outil.construire(code, ident, parametres.chemin_modele("manuel"), secrets=valeurs.values())
    except outil.ErreurManuel as ex:
        flash(request, str(ex), "erreur")
    else:
        base.auditer(u["id"], code, "manuel-mise-en-page", ident)
        flash(request, "Manuel remis en page avec le modèle " + ("de l'entreprise." if s["modele"] == "entreprise" else "interne."), "ok")
    return RedirectResponse(f"/projets/{code}/documents#manuel", status_code=303)


# ---------------------------------------------------------------- paramètres de l'outil

@app.get("/parametres", response_class=HTMLResponse)
def parametres_page(request: Request):
    u = utilisateur(request)
    cx = connexions.resume(connexions.lire(base, u["id"]))
    return page(request, "parametres.html", u=u, cx=cx, ia=parametres.resume_ia(base), docs=parametres.resume_documents(base),
                nb_utilisateurs=(base.un("SELECT COUNT(*) AS n FROM utilisateurs WHERE actif = 1") or {"n": 0})["n"])


_cache_modeles = {"t": 0.0, "v": {}}


def modeles_connus() -> dict:
    """Modèles connus du moteur par fournisseur (liste de suggestions), gardés 10 minutes."""
    import time as _time
    if _time.time() - _cache_modeles["t"] > 600 or not _cache_modeles["v"]:
        v = moteur.modeles_disponibles()
        if v:
            _cache_modeles.update(t=_time.time(), v=v)
    return _cache_modeles["v"]


@app.get("/parametres/modeles", response_class=HTMLResponse)
def parametres_modeles_page(request: Request):
    u = utilisateur(request)
    connus = modeles_connus()
    suggestions = [f"{f}/{m}" for f in (*parametres.FOURNISSEURS, "opencode") for m in connus.get(f, [])][:4000]
    ia = parametres.resume_ia(base, u["id"])
    miennes = parametres.resume_cles_personnelles(base, u["id"])
    # État des clés par fournisseur, pour n'afficher que celles des modèles choisis (page dynamique).
    cles = {f: {"libelle": info["libelle"], "lien": info["lien"], "gratuit": info["gratuit"],
                "entreprise": ia["cles"][f]["fin"] if ia["cles"][f]["enregistree"] else "",
                "serveur": ia["cles"][f]["serveur"], "perso": miennes[f]["fin"] if miennes[f]["enregistree"] else ""}
            for f, info in parametres.FOURNISSEURS.items()}
    choisis = [ia["principal"] or reglages.modele, *ia["usages"].values(), *ia["secours"]]
    return page(request, "parametres_modeles.html", u=u, ia=ia, cles=cles, usages=parametres.USAGES, suggestions=suggestions,
                modifiable=u["role"] == "admin", catalogue=parametres.catalogue_affiche(connus),
                dans_catalogue={m for _, g in parametres.CATALOGUE for m, _, _ in g}, AUTRE=parametres.AUTRE,
                SECOURS_MAX=parametres.SECOURS_MAX,
                necessaires=sorted({m.split("/", 1)[0] for m in choisis if m} & set(parametres.FOURNISSEURS)),
                partage=any(parametres.est_gratuit_partage(m) for m in choisis),
                simulation=reglages.modele.startswith("simulation/"))


AVERTISSEMENTS_ESSAI = ("Aucune clé", "Limite d'utilisation", "Crédit épuisé")


def essayer(modeles, uid) -> tuple:
    """Essaie chaque modèle : (échecs bloquants, avertissements). Une clé absente (chaque utilisateur peut mettre la
    sienne), une limite atteinte ou un crédit épuisé n'empêchent pas d'enregistrer : la chaîne de secours prend le relais."""
    echecs, avertis = [], []
    for m in modeles:
        if m.startswith("simulation/"):
            continue
        reussi, pourquoi = moteur.essayer_modele(m, uid)
        if not reussi:
            (avertis if any(a in pourquoi for a in AVERTISSEMENTS_ESSAI) else echecs).append(f"{m} : {pourquoi}")
    return echecs, avertis


@app.post("/parametres/modeles")
async def parametres_modeles(request: Request):
    form = await request.form()
    controler_csrf(request, str(form.get("csrf") or ""))
    u = exiger_admin(request)
    principal = parametres.choisir(form, "principal")
    usages = {k: parametres.choisir(form, f"usage_{k}") for k in parametres.USAGES}
    secours = [parametres.choisir(form, f"secours_{i}") for i in range(1, parametres.SECOURS_MAX + 1)]
    cles = {f: str(form.get(f"cle_{f}") or "") for f in parametres.FOURNISSEURS}
    retirer = [f for f in parametres.FOURNISSEURS if form.get(f"retirer_{f}")]
    try:
        avant = parametres.enregistrer_ia(base, principal, usages, cles, retirer, u, secours=secours,
                                          gratuits=bool(form.get("gratuits")))
    except parametres.ErreurParametres as e:
        flash(request, f"Paramètres non enregistrés : {e}", "erreur")
        return RedirectResponse("/parametres/modeles", status_code=303)
    ok, detail = moteur.disponible()
    if not ok:
        base.auditer(u["id"], None, "modeles-ia", "enregistrés sans essai (moteur indisponible)")
        flash(request, f"Paramètres enregistrés, mais pas essayés : le moteur est indisponible ({detail}).", "alerte")
        return RedirectResponse("/parametres/modeles", status_code=303)
    echecs, avertis = essayer(parametres.modeles_a_essayer(base), u["id"])
    if echecs:
        parametres.restaurer(base, avant)
        flash(request, "Paramètres non enregistrés : l'essai a échoué.\n" + "\n".join(echecs[:4]), "erreur")
        return RedirectResponse("/parametres/modeles", status_code=303)
    base.auditer(u["id"], None, "modeles-ia", ", ".join(parametres.modeles_a_essayer(base)))
    if avertis:
        flash(request, "Modèles d'IA enregistrés. À noter :\n" + "\n".join(avertis[:6]), "alerte")
    else:
        flash(request, "Modèles d'IA enregistrés : chaque modèle a répondu à un court essai.", "ok")
    return RedirectResponse("/parametres/modeles", status_code=303)


def modele_d_essai(fournisseur: str) -> str:
    """Modèle avec lequel une clé personnelle est essayée : le premier du catalogue pour ce fournisseur."""
    for _, groupe in parametres.CATALOGUE:
        for m, _, _ in groupe:
            if m.split("/", 1)[0] == fournisseur and not parametres.est_gratuit_partage(m):
                return m
    return ""


@app.post("/parametres/modeles/mes-cles")
async def parametres_mes_cles(request: Request):
    """Clés personnelles : chaque utilisateur peut apporter sa clé (gratuite ou non), utilisée pour ses tâches."""
    form = await request.form()
    controler_csrf(request, str(form.get("csrf") or ""))
    u = utilisateur(request)
    cles = {f: str(form.get(f"ma_cle_{f}") or "") for f in parametres.FOURNISSEURS}
    retirer = [f for f in parametres.FOURNISSEURS if form.get(f"retirer_ma_{f}")]
    try:
        avant = parametres.enregistrer_cles_personnelles(base, u, cles, retirer)
    except parametres.ErreurParametres as e:
        flash(request, f"Clés non enregistrées : {e}", "erreur")
        return RedirectResponse("/parametres/modeles#mes-cles", status_code=303)
    nouvelles = [f for f, c in cles.items() if c.strip()]
    echecs, avertis = [], []
    if nouvelles and moteur.disponible()[0]:
        echecs, avertis = essayer([m for m in (modele_d_essai(f) for f in nouvelles) if m], u["id"])
    if echecs:
        parametres.restaurer(base, avant)
        flash(request, "Clés non enregistrées : l'essai a échoué.\n" + "\n".join(echecs[:4]), "erreur")
        return RedirectResponse("/parametres/modeles#mes-cles", status_code=303)
    base.auditer(u["id"], None, "cles-ia-personnelles", ", ".join(nouvelles + [f"retrait {f}" for f in retirer]) or "aucun changement")
    texte = "Vos clés sont enregistrées" + (" et ont répondu à un court essai." if nouvelles and not avertis else ".")
    flash(request, texte + ("\nÀ noter :\n" + "\n".join(avertis) if avertis else ""), "alerte" if avertis else "ok")
    return RedirectResponse("/parametres/modeles#mes-cles", status_code=303)


@app.get("/parametres/documents", response_class=HTMLResponse)
def parametres_documents_page(request: Request):
    u = utilisateur(request)
    return page(request, "parametres_documents.html", u=u, docs=parametres.resume_documents(base),
                modifiable=u["role"] in ("admin", "responsable"),
                marqueurs_cahier=__import__("cahier_modele").MARQUEURS, marqueurs_manuel=__import__("manuel_modele").MARQUEURS)


@app.post("/parametres/documents/{type_}")
async def parametres_documents_deposer(request: Request, type_: str, fichier: UploadFile = File(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = exiger_role(request, "admin", "responsable")
    if type_ not in parametres.DOCUMENTS:
        raise HTTPException(404, "Type de document inconnu.")
    donnees = await fichier.read(30 * 1024 * 1024 + 1)
    try:
        meta = parametres.deposer_modele(base, type_, fichier.filename or "", donnees, u)
    except parametres.ErreurParametres as e:
        flash(request, f"Modèle refusé : {e}", "erreur")
        return RedirectResponse(f"/parametres/documents#{type_}", status_code=303)
    base.auditer(u["id"], None, f"modele-{type_}", meta["nom"])
    flash(request, f"Modèle de {parametres.DOCUMENTS[type_]['libelle'].lower()} enregistré : il sera utilisé pour les prochains documents.", "ok")
    return RedirectResponse(f"/parametres/documents#{type_}", status_code=303)


@app.post("/parametres/documents/{type_}/retirer")
def parametres_documents_retirer(request: Request, type_: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = exiger_role(request, "admin", "responsable")
    if type_ not in parametres.DOCUMENTS:
        raise HTTPException(404, "Type de document inconnu.")
    parametres.retirer_modele(base, type_)
    base.auditer(u["id"], None, f"modele-{type_}-retire")
    flash(request, f"Modèle retiré : le {parametres.DOCUMENTS[type_]['libelle'].lower()} utilisera de nouveau le modèle interne.", "ok")
    return RedirectResponse(f"/parametres/documents#{type_}", status_code=303)


@app.get("/parametres/documents/{type_}/fichier")
def parametres_documents_fichier(request: Request, type_: str, interne: int = 0):
    """Télécharge le modèle de l'entreprise, ou le modèle interne (point de départ pour en faire un)."""
    utilisateur(request)
    info = parametres.DOCUMENTS.get(type_)
    if not info:
        raise HTTPException(404, "Type de document inconnu.")
    if interne:
        f = reglages.racine / "templates" / ("cahier/modele_cahier.xlsx" if type_ == "cahier" else "manuel/modele_manuel.docx")
        return FileResponse(f, filename=f.name)
    f = parametres.chemin_modele(type_)
    if not f:
        raise HTTPException(404, "Aucun modèle de l'entreprise déposé.")
    meta = parametres.lire(base, f"modele:{type_}") or {}
    return FileResponse(f, filename=meta.get("nom") or info["fichier"])


# ---------------------------------------------------------------- activité

@app.get("/activite", response_class=HTMLResponse)
def activite_page(request: Request, projet: str = ""):
    u = utilisateur(request)
    codes = {p["code"]: p["nom"] for p in liste_projets()}
    sql, params = "SELECT t.*, u.nom AS auteur FROM taches t LEFT JOIN utilisateurs u ON u.id = t.cree_par", []
    if projet and projet in codes:
        sql += " WHERE t.projet = ?"
        params.append(projet)
    lignes = []
    for t in base.tous(sql + " ORDER BY t.id DESC LIMIT 100", tuple(params)):
        if t["projet"] not in codes:
            continue
        try:
            journal = json.loads(t["journal"] or "[]")
        except ValueError:
            journal = []
        lignes.append({"id": t["id"], "projet": t["projet"], "nom_projet": codes[t["projet"]],
                       "type": TYPES_TACHES.get(t["type"], t["type"]), "statut": t["statut"],
                       "statut_libelle": STATUTS_TACHES.get(t["statut"], t["statut"]), "auteur": t["auteur"] or "",
                       "debut": (t["debut"] or t["cree_le"] or "")[:16].replace("T", " à "),
                       "dernier": (journal[-1]["m"] if journal else "")[:220]})
    return page(request, "activite.html", u=u, lignes=lignes, projets_=codes, filtre=projet)


# ---------------------------------------------------------------- relais vers le fournisseur d'IA (moteur uniquement)

@app.api_route("/ia/{fournisseur}/{chemin:path}", methods=["GET", "POST"], include_in_schema=False)
async def relais_fournisseur(request: Request, fournisseur: str, chemin: str):
    """Appelé par le moteur OpenCode avec le jeton interne, jamais par le navigateur (pas de session)."""
    from starlette.concurrency import run_in_threadpool
    uid = await run_in_threadpool(moteur.utilisateur_de_session, base, request.headers.get("x-opencode-session-id", ""))
    return await relais_ia.relayer(request, fournisseur, chemin, parametres.cle_pour(base, fournisseur, uid))
