# -*- coding: utf-8 -*-
"""Tests de l'application par l'agent (temps B) : application testée, comptes de test, navigateur de la tâche.

- Les comptes de test sont chiffrés comme les connexions Squash (app/connexions.py). Ils ne sont
  donnés qu'au navigateur de la tâche, sous forme de secrets : l'agent saisit le NOM du secret
  (COMPTE_1_MOT_DE_PASSE), le MCP Playwright saisit la valeur et la masque dans ses réponses.
- Le navigateur est un serveur MCP Playwright ajouté au moteur pour la durée de la tâche
  (saas/navigateur_mcp.mjs) : sans affichage, sans profil conservé, limité aux domaines de
  l'application testée.
- Le lien de l'application passe la même garde réseau que Squash.
"""
import re
from urllib.parse import urlsplit

from . import connexions, projets
from .config import reglages
from .db import maintenant

ACTIONS = {"lecture-seule": "Lecture seule : l'assistant ne crée, ne modifie ni ne supprime aucune donnée",
           "donnees-de-test": "Il peut créer des données de test (jamais de suppression ni de paiement réel)"}
MAX_COMPTES = 5
VERSION_MCP = "0.0.84"


class ErreurCampagne(Exception):
    pass


# ---------------------------------------------------------------- application testée

def normaliser_lien(saisie: str) -> str:
    s = (saisie or "").strip()
    if not s:
        raise ErreurCampagne("Indiquez le lien de l'application à tester.")
    if len(s) > 500:
        raise ErreurCampagne("Lien trop long.")
    if "://" not in s:
        s = "https://" + s
    p = urlsplit(s)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ErreurCampagne("Lien invalide : il ressemble à https://recette.mon-application.com.")
    if p.username or p.password:
        raise ErreurCampagne("Le lien ne doit pas contenir d'identifiant : ajoutez un compte de test à la place.")
    return f"{p.scheme}://{p.netloc.lower()}{p.path or '/'}" + (f"?{p.query}" if p.query else "")


def origine(lien: str) -> str:
    p = urlsplit(lien)
    return f"{p.scheme}://{p.netloc.lower()}"


def application(code: str) -> dict:
    a = projets.fiche(code).get("application") or {}
    actions = a.get("actions_autorisees")
    return {"url": a.get("url") or "", "actions": actions if actions in ACTIONS else "lecture-seule",
            "autres_domaines": [d for d in a.get("autres_domaines") or [] if isinstance(d, str)]}


def enregistrer_application(code: str, url: str, actions: str, autres_domaines: str) -> dict:
    lien = normaliser_lien(url)
    if actions not in ACTIONS:
        raise ErreurCampagne("Choisissez ce que l'assistant a le droit de faire.")
    domaines = []
    for ligne in re.split(r"[\s,;]+", autres_domaines or ""):
        if ligne.strip():
            domaines.append(origine(normaliser_lien(ligne)))
    if len(domaines) > 5:
        raise ErreurCampagne("Cinq autres domaines au plus.")
    for adresse in [lien, *domaines]:
        verifier_reseau(adresse)
    f = projets.fiche(code)
    a = f.setdefault("application", {})
    a.update(url=lien, actions_autorisees=actions, autres_domaines=sorted(set(domaines) - {origine(lien)}))
    projets.ecrire_fiche(code, f)
    return application(code)


def verifier_reseau(lien: str):
    try:
        connexions.verifier_reseau(lien, "de l'application")
    except connexions.ErreurConnexion as e:
        raise ErreurCampagne(str(e))


# ---------------------------------------------------------------- comptes de test

def comptes(base, code: str) -> list:
    """Comptes affichables : jamais le mot de passe, l'identifiant en clair (ce n'est pas un secret)."""
    res = []
    for c in base.tous("SELECT id, libelle, identifiant, maj_le FROM comptes_test WHERE projet = ? ORDER BY id", (code,)):
        try:
            ident = connexions.dechiffrer(c["identifiant"])
        except connexions.ErreurConnexion:
            ident = "(illisible)"
        res.append({"id": c["id"], "libelle": c["libelle"], "identifiant": ident, "maj_le": (c["maj_le"] or "")[:16].replace("T", " à ")})
    return res


def ajouter_compte(base, code: str, libelle: str, identifiant: str, mot_de_passe: str, utilisateur_id: int):
    libelle, identifiant = (libelle or "").strip()[:80], (identifiant or "").strip()[:200]
    if not libelle or not identifiant or not mot_de_passe:
        raise ErreurCampagne("Indiquez le rôle du compte, son identifiant et son mot de passe.")
    if "\n" in identifiant + mot_de_passe or len(mot_de_passe) > 500:
        raise ErreurCampagne("Identifiant ou mot de passe invalide.")
    if len(base.tous("SELECT id FROM comptes_test WHERE projet = ?", (code,))) >= MAX_COMPTES:
        raise ErreurCampagne(f"{MAX_COMPTES} comptes de test au plus par projet.")
    base.x("INSERT INTO comptes_test (projet, libelle, identifiant, secret, cree_par, maj_le) VALUES (?,?,?,?,?,?)",
           (code, libelle, connexions.chiffrer(identifiant), connexions.chiffrer(mot_de_passe), utilisateur_id, maintenant()))


def supprimer_compte(base, code: str, compte_id: int):
    base.x("DELETE FROM comptes_test WHERE projet = ? AND id = ?", (code, compte_id))


def secrets(base, code: str) -> tuple:
    """(libellés dans l'ordre, secrets {NOM: valeur}) pour le navigateur de la tâche."""
    libelles, valeurs = [], {}
    for i, c in enumerate(base.tous("SELECT * FROM comptes_test WHERE projet = ? ORDER BY id", (code,)), start=1):
        libelles.append(c["libelle"])
        valeurs[f"COMPTE_{i}_IDENTIFIANT"] = connexions.dechiffrer(c["identifiant"])
        valeurs[f"COMPTE_{i}_MOT_DE_PASSE"] = connexions.dechiffrer(c["secret"])
    return libelles, valeurs


# ---------------------------------------------------------------- navigateur de la tâche

def nom_navigateur(tid: int) -> str:
    return f"nav{int(tid)}"


def configuration_navigateur(tid: int, app: dict, valeurs: dict, dossier_campagne) -> dict:
    """Serveur MCP Playwright de la tâche, au format de l'API OpenCode (POST /mcp)."""
    origines = ";".join([origine(app["url"]), *app["autres_domaines"]])
    env = {"QAF_NAV_SECRETS": __import__("json").dumps(valeurs), "QAF_NAV_ORIGINES": origines,
           "QAF_NAV_VERSION": VERSION_MCP}
    return {"type": "local", "command": ["node", str(reglages.racine / "saas" / "navigateur_mcp.mjs")],
            "cwd": str(dossier_campagne), "environment": env, "timeout": 60000}


def outils_autorises(tid: int) -> dict:
    """Outils visibles par l'agent pendant la tâche : seulement le navigateur de cette tâche."""
    return {"nav*": False, f"{nom_navigateur(tid)}_*": True}
