# -*- coding: utf-8 -*-
"""Application web QA Factory SaaS (FastAPI, pages rendues côté serveur).

Parcours (skill interface-qa-factory) : déposer -> génération -> fichiers produits -> relecture
et enregistrement (= validation) -> envoi dans Squash.

Lancement : uvicorn app.main:app --app-dir saas --host 0.0.0.0 --port 8000
"""
import json
import os
from collections import Counter
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import projets
from .config import ICI, reglages
from .db import STATUTS_ACTIFS, Base, maintenant
from .moteur import ErreurMoteur, moteur
from .securite import ROLES, controler_csrf, hacher, jeton_csrf, mot_de_passe_valable, verifier
from .taches import ErreurTache, gestionnaire, progression

reglages.preparer()
import vues_cas  # noqa: E402  (outils/ est ajouté au chemin par reglages.preparer)

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
        reponse["simulation"] = {"projet": r.get("projet"), "resume": r.get("resume")}
    if t["type"] == "publier" and t["statut"] == "termine":
        reponse["crees"] = len(r.get("crees") or [])
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
                squash_id=(projets.fiche(code).get("squash") or {}).get("projet_id"))


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
    nom_dossier, _ = dossier_lecture(code)
    return page(request, "questions.html", u=u, code=code, fiche=projets.fiche(code), dossier=nom_dossier,
                questions=projets.questions(code, nom_dossier))


@app.get("/projets/{code}/donnees", response_class=HTMLResponse)
def donnees_page(request: Request, code: str):
    u = utilisateur(request)
    exiger_projet(code)
    nom_dossier, _ = dossier_lecture(code)
    return page(request, "donnees.html", u=u, code=code, fiche=projets.fiche(code), dossier=nom_dossier,
                jeux=projets.jeux(code, nom_dossier))


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

@app.post("/projets/{code}/squash/simuler")
async def squash_simuler(request: Request, code: str):
    corps = await json_controle(request)
    u = utilisateur(request)
    exiger_projet(code)
    sid = str(corps.get("squash_id") or "").strip()
    fiche = projets.fiche(code)
    if sid:
        if not sid.isdigit():
            raise HTTPException(400, "Le numéro du projet Squash est un nombre (il figure dans l'adresse du projet dans Squash).")
        fiche.setdefault("squash", {})["projet_id"] = int(sid)
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
        raise HTTPException(400, "Indiquez le numéro du projet dans Squash.")
    try:
        tid = gestionnaire.soumettre(code, "publier-simulation", u)
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
    resume = r.get("resume") or {}
    deja = 0
    try:
        c = json.loads((projets.dossier(code) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
        deja = sum(len(c.get(k) or {}) for k in ("exigences", "cas_de_tests", "dossiers_exigences", "dossiers_cas"))
    except Exception:  # noqa: BLE001
        pass
    try:
        tid = gestionnaire.soumettre(code, "publier", u, {"empreinte": r.get("empreinte"), "simulation": s["id"],
                                                          "a_creer": int(resume.get("creer", 0)) + int(resume.get("recreer", 0)),
                                                          "deja": deja})
    except ErreurTache as e:
        raise HTTPException(409, str(e))
    return {"tache": tid}


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
