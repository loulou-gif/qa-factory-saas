# -*- coding: utf-8 -*-
"""Application web QA Factory SaaS (FastAPI, pages rendues côté serveur).

Lancement : uvicorn app.main:app --app-dir saas --host 0.0.0.0 --port 8000
"""
import html
import json
import os
from contextlib import asynccontextmanager
from typing import List

import markdown as md
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import projets
from .config import ICI, reglages
from .db import STATUTS_ACTIFS, Base, maintenant
from .moteur import ErreurMoteur, moteur
from .securite import (ROLES, controler_csrf, hacher, jeton_csrf, mot_de_passe_valable, peut_creer_projet,
                       peut_valider, verifier)
from .taches import STATUTS, TYPES, ErreurTache, gestionnaire

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
gabarits.env.globals.update(ROLES=ROLES, TYPES=TYPES, STATUTS=STATUTS, lib=vues_cas)


@app.exception_handler(Redirection)
async def _redirection(request, exc):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(HTTPException)
async def _erreur_http(request, exc):
    return gabarits.TemplateResponse(request, "erreur.html", {"u": utilisateur(request, obligatoire=False), "message": exc.detail,
                                                               "csrf": jeton_csrf(request)}, status_code=exc.status_code)


# ---------------------------------------------------------------- outils de page

def utilisateur(request: Request, obligatoire=True):
    uid = request.session.get("uid")
    u = base.un("SELECT * FROM utilisateurs WHERE id = ? AND actif = 1", (uid,)) if uid else None
    if not u and obligatoire:
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


def projet_db(code):
    return base.un("SELECT p.*, u.nom AS responsable_nom FROM projets p LEFT JOIN utilisateurs u ON u.id = p.responsable_id "
                   "WHERE p.code = ?", (code,))


def exiger_projet(code):
    if not projets.existe(code):
        raise HTTPException(404, "Projet introuvable.")
    return projet_db(code)


def exiger_validateur(u, pdb):
    if not peut_valider(u, pdb):
        raise HTTPException(403, "Réservé au responsable du projet ou à un administrateur.")


def vers_projet(code, ancre=""):
    return RedirectResponse(f"/projets/{code}{'#' + ancre if ancre else ''}", status_code=303)


def rendu_markdown(texte):
    return md.markdown(html.escape(texte, quote=False), extensions=["tables", "sane_lists"])


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


# ---------------------------------------------------------------- projets

@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    u = utilisateur(request)
    liste = []
    for code in projets.lister():
        try:
            f, e = projets.fiche(code), projets.etat(code)
        except Exception:  # noqa: BLE001
            continue
        liste.append({"code": code, "nom": f.get("nom", code), "url": (f.get("application") or {}).get("url"), "etat": e,
                      "db": projet_db(code), "active": gestionnaire.active(code)})
    ok, detail = moteur.disponible()
    return page(request, "accueil.html", u=u, projets=liste, moteur_ok=ok, moteur_detail=detail,
                peut_creer=peut_creer_projet(u))


@app.get("/projets/nouveau", response_class=HTMLResponse)
def nouveau_page(request: Request):
    u = utilisateur(request)
    if not peut_creer_projet(u):
        raise HTTPException(403, "Réservé aux responsables de projet et aux administrateurs.")
    resp = base.tous("SELECT id, nom FROM utilisateurs WHERE actif = 1 AND role IN ('admin', 'responsable') ORDER BY nom")
    return page(request, "projet_nouveau.html", u=u, responsables=resp)


@app.post("/projets/nouveau")
def nouveau(request: Request, code: str = Form(...), nom: str = Form(""), url: str = Form(""), squash_id: str = Form(""),
            responsable_id: int = Form(0), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    if not peut_creer_projet(u):
        raise HTTPException(403, "Réservé aux responsables de projet et aux administrateurs.")
    code = code.strip().lower()
    resp = base.un("SELECT id, nom FROM utilisateurs WHERE id = ? AND actif = 1", (responsable_id or u["id"],)) or u
    try:
        if squash_id.strip() and not squash_id.strip().isdigit():
            raise projets.ErreurProjet("L'ID Squash est un nombre (laisser vide si le projet Squash n'existe pas encore).")
        if url.strip() and not url.strip().startswith(("http://", "https://")):
            raise projets.ErreurProjet("L'adresse du site doit commencer par http:// ou https:// (laisser vide si le site n'existe pas encore).")
        projets.creer(code, nom.strip(), url.strip(), squash_id.strip(), resp["nom"])
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
        return RedirectResponse("/projets/nouveau", status_code=303)
    base.x("INSERT OR REPLACE INTO projets (code, responsable_id, cree_par, cree_le) VALUES (?,?,?,?)",
           (code, resp["id"], u["id"], maintenant()))
    base.auditer(u["id"], code, "creation-projet")
    flash(request, "Projet créé. Étape suivante : déposer le cahier des charges.", "ok")
    return vers_projet(code)


@app.get("/projets/{code}", response_class=HTMLResponse)
def projet_page(request: Request, code: str):
    u = utilisateur(request)
    pdb = exiger_projet(code)
    e = projets.etat(code)
    derniere_simu = base.un("SELECT id FROM taches WHERE projet = ? AND type = 'publier-simulation' AND statut = 'termine' "
                            "ORDER BY id DESC LIMIT 1", (code,))
    simu = base.tache(derniere_simu["id"]) if derniere_simu else None
    if simu and e["valide"]:
        from qa_commun import empreinte
        f = projets.dossier(code) / "03-valide" / "cas-de-tests.json"
        if (simu["resultat"] or {}).get("empreinte") != empreinte(f):
            simu = None
    modifiees = []
    if e["a_valider"]:
        from rendre_revue import vues_modifiees
        modifiees = vues_modifiees(projets.dossier(code) / "02-a-valider")
    taches = base.tous("SELECT t.id, t.type, t.statut, t.cree_le, u.nom AS auteur FROM taches t LEFT JOIN utilisateurs u "
                       "ON u.id = t.cree_par WHERE projet = ? ORDER BY t.id DESC LIMIT 8", (code,))
    resp = base.tous("SELECT id, nom FROM utilisateurs WHERE actif = 1 AND role IN ('admin', 'responsable') ORDER BY nom")
    return page(request, "projet.html", u=u, code=code, fiche=projets.fiche(code), pdb=pdb, e=e,
                validateur=peut_valider(u, pdb), active=gestionnaire.active(code), simu=simu, taches=taches,
                journal=projets.lire_journal(code)[:12], modifiees=modifiees, responsables=resp,
                synchro=request.session.pop("synchro", None),
                docs_entrants=projets.contenu(projets.dossier(code) / "01-entrant"),
                extensions=", ".join(sorted(projets.EXTENSIONS_DOCUMENTS)))


@app.post("/projets/{code}/fiche")
def fiche_maj(request: Request, code: str, nom: str = Form(""), client: str = Form(""), url: str = Form(""),
              environnement: str = Form(""), actions_autorisees: str = Form(""), squash_id: str = Form(""),
              responsable_id: int = Form(0), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    pdb = exiger_projet(code)
    exiger_validateur(u, pdb)
    f = projets.fiche(code)
    if url.strip() and not url.strip().startswith(("http://", "https://")):
        flash(request, "L'adresse du site doit commencer par http:// ou https://.", "erreur")
        return vers_projet(code, "fiche")
    if squash_id.strip() and not squash_id.strip().isdigit():
        flash(request, "L'ID Squash est un nombre.", "erreur")
        return vers_projet(code, "fiche")
    f["nom"] = nom.strip() or f.get("nom", code)
    f["client"] = client.strip() or "À renseigner"
    app_ = f.setdefault("application", {})
    app_["url"] = url.strip()
    app_["environnement"] = environnement.strip() or "À confirmer"
    if actions_autorisees.strip():
        app_["actions_autorisees"] = actions_autorisees.strip()
    f.setdefault("squash", {})["projet_id"] = int(squash_id) if squash_id.strip() else None
    if responsable_id and u["role"] == "admin":
        r = base.un("SELECT id, nom FROM utilisateurs WHERE id = ? AND actif = 1", (responsable_id,))
        if r:
            f["responsable"] = r["nom"]
            base.x("INSERT INTO projets (code, responsable_id, cree_par, cree_le) VALUES (?,?,?,?) "
                   "ON CONFLICT(code) DO UPDATE SET responsable_id = excluded.responsable_id", (code, r["id"], u["id"], maintenant()))
    projets.ecrire_fiche(code, f)
    base.auditer(u["id"], code, "fiche", json.dumps({"url": app_["url"], "squash": f["squash"]["projet_id"]}))
    flash(request, "Fiche du projet enregistrée.", "ok")
    return vers_projet(code, "fiche")


@app.post("/projets/{code}/documents")
async def documents(request: Request, code: str, fichiers: List[UploadFile] = File(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    noms = []
    for f in fichiers:
        if not f.filename:
            continue
        try:
            noms.append(projets.deposer_document(code, f.filename, await f.read()))
        except projets.ErreurProjet as e:
            flash(request, f"{f.filename} : {e}", "erreur")
    if noms:
        base.auditer(u["id"], code, "depot-documents", ", ".join(noms))
        flash(request, f"Déposé : {', '.join(noms)}.", "ok")
    return vers_projet(code, "documents")


@app.post("/projets/{code}/documents/retirer")
def document_retirer(request: Request, code: str, nom: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    try:
        projets.retirer_document(code, nom)
        base.auditer(u["id"], code, "retrait-document", nom)
        flash(request, f"Retiré : {nom}.", "ok")
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
    return vers_projet(code, "documents")


def lancer(request, code, type_, parametres=None):
    u = utilisateur(request)
    try:
        tid = gestionnaire.soumettre(code, type_, u, parametres)
    except ErreurTache as e:
        flash(request, str(e), "erreur")
        return vers_projet(code)
    return RedirectResponse(f"/taches/{tid}", status_code=303)


@app.post("/projets/{code}/analyser")
def analyser(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    exiger_projet(code)
    e = projets.etat(code)
    if not e["documents"]:
        flash(request, "Déposer d'abord le cahier des charges.", "erreur")
        return vers_projet(code, "documents")
    if e["a_valider"] or e["valide"]:
        flash(request, "L'analyse existe déjà : utiliser les corrections.", "erreur")
        return vers_projet(code)
    ok, detail = moteur.disponible()
    if not ok:
        flash(request, f"Analyse impossible : {detail}.", "erreur")
        return vers_projet(code)
    return lancer(request, code, "analyser")


@app.post("/projets/{code}/corriger")
def corriger(request: Request, code: str, demande: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    exiger_projet(code)
    if not demande.strip():
        flash(request, "Écrire la correction demandée.", "erreur")
        return vers_projet(code, "relecture")
    if len(demande) > 4000:
        flash(request, "Demande trop longue (4 000 caractères au plus).", "erreur")
        return vers_projet(code, "relecture")
    return lancer(request, code, "corriger", {"demande": demande.strip()})


@app.post("/projets/{code}/vue")
async def vue(request: Request, code: str, fichier: UploadFile = File(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    if gestionnaire.active(code):
        flash(request, "Une tâche est en cours sur ce projet : attendre sa fin avant de renvoyer un fichier.", "erreur")
        return vers_projet(code, "relecture")
    try:
        r = projets.televerser_vue(code, fichier.filename or "", await fichier.read())
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
        return vers_projet(code, "relecture")
    base.auditer(u["id"], code, "renvoi-fichier", fichier.filename)
    request.session["synchro"] = {**r, "sortie": r["sortie"][-1500:]}
    if r["conflit"]:
        flash(request, "L'Excel et le Word ont été modifiés différemment : choisir lequel garder.", "erreur")
    elif r["code"]:
        flash(request, "Modifications reportées, mais le contrôle signale des erreurs : voir le détail.", "erreur")
    else:
        flash(request, f"{fichier.filename} pris en compte : JSON, Markdown et l'autre fichier sont à jour.", "ok")
    return vers_projet(code, "relecture")


@app.post("/projets/{code}/conflit")
def conflit(request: Request, code: str, source: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    exiger_projet(code)
    if source not in ("xlsx", "docx"):
        raise HTTPException(400, "Choix invalide.")
    r = projets.synchroniser(code, source)
    request.session["synchro"] = {**r, "sortie": r["sortie"][-1500:]}
    base.auditer(u["id"], code, "conflit-resolu", source)
    flash(request, f"Version {'Excel' if source == 'xlsx' else 'Word'} retenue ; l'autre fichier est régénéré.", "ok" if not r["code"] else "erreur")
    return vers_projet(code, "relecture")


@app.post("/projets/{code}/valider")
def valider(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    pdb = exiger_projet(code)
    exiger_validateur(u, pdb)
    if gestionnaire.active(code):
        flash(request, "Une tâche est en cours sur ce projet.", "erreur")
        return vers_projet(code)
    try:
        from rendre_revue import vues_modifiees
        if vues_modifiees(projets.dossier(code) / "02-a-valider"):
            raise projets.ErreurProjet("L'Excel ou le Word contient des modifications non reportées : les renvoyer d'abord.")
        projets.valider(code, u["nom"])
        base.auditer(u["id"], code, "validation")
        flash(request, "Analyse validée. Étape suivante : publication dans Squash.", "ok")
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
    return vers_projet(code)


@app.post("/projets/{code}/relecture")
def remettre(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    pdb = exiger_projet(code)
    exiger_validateur(u, pdb)
    try:
        projets.remettre_en_relecture(code, u["nom"])
        base.auditer(u["id"], code, "remise-en-relecture")
        flash(request, "Version validée remise en relecture.", "ok")
    except projets.ErreurProjet as e:
        flash(request, str(e), "erreur")
    return vers_projet(code)


@app.post("/projets/{code}/publier/simulation")
def publier_simulation(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    pdb = exiger_projet(code)
    exiger_validateur(utilisateur(request), pdb)
    return lancer(request, code, "publier-simulation")


@app.post("/projets/{code}/publier")
def publier(request: Request, code: str, simulation: int = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    pdb = exiger_projet(code)
    exiger_validateur(utilisateur(request), pdb)
    s = base.tache(simulation)
    if not s or s["projet"] != code or s["type"] != "publier-simulation" or s["statut"] != "termine":
        flash(request, "Lancer d'abord une simulation.", "erreur")
        return vers_projet(code, "publication")
    return lancer(request, code, "publier", {"empreinte": (s["resultat"] or {}).get("empreinte"), "simulation": simulation})


@app.post("/projets/{code}/specs")
def specs(request: Request, code: str, csrf: str = Form("")):
    controler_csrf(request, csrf)
    exiger_projet(code)
    return lancer(request, code, "specs")


@app.get("/projets/{code}/cas/{dossier}", response_class=HTMLResponse)
def relecture(request: Request, code: str, dossier: str):
    u = utilisateur(request)
    exiger_projet(code)
    nom = {"a-valider": "02-a-valider", "valide": "03-valide"}.get(dossier)
    data = projets.charger_cas(code, nom) if nom else None
    if not data:
        raise HTTPException(404, "Pas de cas de tests dans ce dossier.")
    from qa_commun import fonctionnalites, lire_questions
    qs = lire_questions(projets.dossier(code) / nom / "ambiguites.md")
    from collections import Counter
    return page(request, "relecture.html", u=u, code=code, fiche=projets.fiche(code), data=data, dossier=dossier, nom_dossier=nom,
                fonctionnalites=fonctionnalites(data),
                bloquantes={q for q, v in qs.items() if v["statut"] == "ouverte" and v["gravite"] == "bloquante"},
                par_nature=Counter(c.get("type") for c in data.get("cas_de_tests", [])),
                par_type=Counter(c.get("type_test") for c in data.get("cas_de_tests", [])),
                par_technique=Counter(c.get("technique") for c in data.get("cas_de_tests", [])))


@app.get("/projets/{code}/lire/{dossier}/{nom}", response_class=HTMLResponse)
def lire_markdown(request: Request, code: str, dossier: str, nom: str):
    u = utilisateur(request)
    exiger_projet(code)
    if dossier not in ("02-a-valider", "03-valide") or nom not in ("ambiguites.md", "jeux-de-donnees.md", "matrice-tracabilite.md"):
        raise HTTPException(404, "Document introuvable.")
    f = projets.dossier(code) / dossier / nom
    if not f.exists():
        raise HTTPException(404, "Document introuvable.")
    return page(request, "document.html", u=u, code=code, fiche=projets.fiche(code), titre=nom, dossier=dossier,
                contenu=rendu_markdown(f.read_text(encoding="utf-8")))


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


# ---------------------------------------------------------------- tâches

@app.get("/taches/{tid}", response_class=HTMLResponse)
def tache_page(request: Request, tid: int):
    u = utilisateur(request)
    t = base.tache(tid)
    if not t:
        raise HTTPException(404, "Tâche introuvable.")
    pdb = projet_db(t["projet"])
    return page(request, "tache.html", u=u, t=t, fiche=projets.fiche(t["projet"]) if projets.existe(t["projet"]) else {},
                validateur=peut_valider(u, pdb), actifs=STATUTS_ACTIFS)


@app.get("/taches/{tid}/etat", response_class=HTMLResponse)
def tache_etat(request: Request, tid: int):
    u = utilisateur(request)
    t = base.tache(tid)
    if not t:
        raise HTTPException(404, "Tâche introuvable.")
    # Fragment rafraîchi par la page de la tâche : ne pas consommer les messages flash.
    return gabarits.TemplateResponse(request, "_tache_etat.html", {"u": u, "t": t, "actifs": STATUTS_ACTIFS, "csrf": jeton_csrf(request)})


@app.post("/taches/{tid}/arreter")
def tache_arreter(request: Request, tid: int, csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    gestionnaire.annuler(tid, u)
    return RedirectResponse(f"/taches/{tid}", status_code=303)


@app.post("/taches/{tid}/permission")
def tache_permission(request: Request, tid: int, demande: str = Form(...), decision: str = Form(...), csrf: str = Form("")):
    controler_csrf(request, csrf)
    u = utilisateur(request)
    t = base.tache(tid)
    if not t or not any(a.get("id") == demande for a in (t["attente"] or [])):
        flash(request, "Cette demande n'est plus en attente.", "info")
        return RedirectResponse(f"/taches/{tid}", status_code=303)
    detail = next(a for a in t["attente"] if a["id"] == demande)
    try:
        moteur.repondre_permission(demande, decision == "accepter", "" if decision == "accepter" else f"Refusé par {u['nom']}")
        base.ajouter_journal(tid, f"{'Autorisé' if decision == 'accepter' else 'Refusé'} par {u['nom']} : {detail.get('permission')} "
                                  f"{detail.get('detail', '')}")
        base.auditer(u["id"], t["projet"], f"permission:{decision}", detail.get("detail", ""))
        base.maj_tache(tid, attente=[a for a in t["attente"] if a["id"] != demande] or None)
    except ErreurMoteur as e:
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/taches/{tid}", status_code=303)


@app.post("/taches/{tid}/question")
async def tache_question(request: Request, tid: int):
    form = await request.form()
    controler_csrf(request, form.get("csrf", ""))
    u = utilisateur(request)
    t = base.tache(tid)
    demande = form.get("demande", "")
    q = next((a for a in (t["attente"] or []) if a.get("id") == demande and a["genre"] == "question"), None) if t else None
    if not q:
        flash(request, "Cette question n'est plus en attente.", "info")
        return RedirectResponse(f"/taches/{tid}", status_code=303)
    try:
        if form.get("decision") == "ignorer":
            moteur.rejeter_question(demande)
            base.ajouter_journal(tid, f"Question écartée par {u['nom']}.")
        else:
            reponses = []
            for i, _ in enumerate(q["questions"]):
                choix = form.getlist(f"q{i}")
                libre = (form.get(f"libre{i}") or "").strip()
                reponses.append([c for c in choix if c] + ([libre] if libre else []))
            moteur.repondre_question(demande, reponses)
            base.ajouter_journal(tid, f"Réponse de {u['nom']} : " + " | ".join(", ".join(r) for r in reponses))
        base.maj_tache(tid, attente=[a for a in t["attente"] if a["id"] != demande] or None)
    except ErreurMoteur as e:
        flash(request, str(e), "erreur")
    return RedirectResponse(f"/taches/{tid}", status_code=303)


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
