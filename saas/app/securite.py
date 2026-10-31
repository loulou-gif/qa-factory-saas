# -*- coding: utf-8 -*-
"""Comptes, mots de passe, sessions, rôles et protection CSRF."""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

ROLES = {"admin": "Administrateur", "responsable": "Responsable de projet", "testeur": "Testeur"}
LONGUEUR_MIN = 10


def hacher(mot_de_passe: str) -> str:
    sel = secrets.token_bytes(16)
    h = hashlib.scrypt(mot_de_passe.encode(), salt=sel, n=2 ** 14, r=8, p=1)
    return f"scrypt${sel.hex()}${h.hex()}"


def verifier(mot_de_passe: str, stocke: str) -> bool:
    try:
        _, sel, h = stocke.split("$")
        calc = hashlib.scrypt(mot_de_passe.encode(), salt=bytes.fromhex(sel), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def mot_de_passe_valable(mdp: str) -> str:
    """Message d'erreur, ou chaîne vide si le mot de passe convient."""
    if len(mdp) < LONGUEUR_MIN:
        return f"au moins {LONGUEUR_MIN} caractères"
    if mdp.isalpha() or mdp.isdigit():
        return "mélanger lettres et chiffres (ou symboles)"
    return ""


def jeton_csrf(request: Request) -> str:
    j = request.session.get("csrf")
    if not j:
        j = secrets.token_urlsafe(32)
        request.session["csrf"] = j
    return j


def controler_csrf(request: Request, recu: str):
    attendu = request.session.get("csrf")
    if not attendu or not recu or not hmac.compare_digest(attendu, recu):
        raise HTTPException(400, "Formulaire expiré : recharger la page et recommencer.")


def peut_valider(utilisateur, projet_db) -> bool:
    """Valider, remettre en relecture, publier dans Squash : le responsable du projet ou un administrateur."""
    if not utilisateur:
        return False
    if utilisateur["role"] == "admin":
        return True
    return bool(projet_db) and projet_db.get("responsable_id") == utilisateur["id"]


def peut_creer_projet(utilisateur) -> bool:
    return bool(utilisateur) and utilisateur["role"] in ("admin", "responsable")
