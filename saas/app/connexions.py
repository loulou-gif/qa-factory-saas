# -*- coding: utf-8 -*-
"""Connexion de chaque utilisateur à son propre Squash TM : adresse, compte et secret chiffré.

- Le secret (mot de passe ou jeton d'API) est chiffré dans la base (Fernet). La clé vient de
  QAF_CLE_SECRETS ou, à défaut, d'un fichier créé dans le dossier des données : elle ne quitte
  jamais le conteneur web (le moteur IA ne monte pas ce dossier et ne reçoit pas la variable).
- Une connexion n'est enregistrée qu'après un test réussi auprès de Squash.
- Tous les appels à Squash passent par le code du MCP squash-tm (saas/publier_squash.mjs),
  lancé avec les identifiants de l'utilisateur dans le seul environnement de ce processus.
- Par défaut, une adresse qui mène à un réseau interne est refusée (le serveur ne doit pas
  servir de relais vers ses propres réseaux). QAF_SQUASH_RESEAU_PRIVE=true l'autorise, pour
  une installation sur le réseau d'une entreprise ou pour les essais. Le module Node refait ce
  contrôle sur l'adresse IP réellement utilisée à chaque connexion et ne suit pas les redirections
  (saas/reseau_public.mjs) : un nom qui changerait de réponse entre-temps est refusé aussi.
"""
import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from .config import reglages
from .db import maintenant

SUFFIXE_API = "/api/rest/latest"
# Le jeton est proposé en premier : révocable, limité dans le temps, sans exposer le mot de passe.
MODES = {"jeton": "Jeton d'API (recommandé)", "compte": "Identifiant et mot de passe"}
# Variables du serveur qui ne doivent jamais atteindre le module Squash.
PREFIXES_RETIRES = ("SQUASH_TM_", "QAF_", "OPENROUTER", "OPENCODE_")


class ErreurConnexion(Exception):
    pass


# ---------------------------------------------------------------- chiffrement

_chiffreur = None


def chiffreur() -> Fernet:
    global _chiffreur
    if _chiffreur is None:
        cle = os.environ.get("QAF_CLE_SECRETS", "").strip()
        if not cle:
            f = reglages.donnees / ".cle-secrets"
            if not f.exists():
                f.write_text(Fernet.generate_key().decode(), encoding="utf-8")
                try:
                    os.chmod(f, 0o600)
                except OSError:
                    pass
            cle = f.read_text(encoding="utf-8").strip()
        try:
            _chiffreur = Fernet(cle.encode())
        except ValueError:
            raise ErreurConnexion("Clé de chiffrement du serveur invalide (QAF_CLE_SECRETS) : prévenez l'administrateur.")
    return _chiffreur


def chiffrer(texte: str) -> str:
    return chiffreur().encrypt(texte.encode()).decode()


def dechiffrer(texte: str) -> str:
    try:
        return chiffreur().decrypt(texte.encode()).decode()
    except InvalidToken:
        raise ErreurConnexion("Le secret Squash enregistré ne peut plus être lu (clé du serveur changée) : "
                              "saisissez-le à nouveau dans la page Squash.")


# ---------------------------------------------------------------- adresse

def normaliser_adresse(saisie: str) -> str:
    """Adresse de l'API (…/api/rest/latest) à partir de ce que l'utilisateur colle :
    l'adresse de Squash dans le navigateur, avec ou sans https://, avec ou sans /api/rest/…"""
    s = (saisie or "").strip()
    if not s:
        raise ErreurConnexion("Indiquez l'adresse de votre Squash.")
    if len(s) > 500:
        raise ErreurConnexion("Adresse trop longue.")
    if "://" not in s:
        s = "https://" + s
    p = urlsplit(s)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ErreurConnexion("Adresse invalide : elle ressemble à https://squash.mon-entreprise.com/squash.")
    if p.username or p.password:
        raise ErreurConnexion("L'adresse ne doit pas contenir d'identifiant : saisissez-le dans les champs prévus.")
    chemin = p.path.rstrip("/")
    i = chemin.find("/api/rest/")
    if i >= 0:
        chemin = chemin[:i]
    return f"{p.scheme}://{p.netloc.lower()}{chemin}{SUFFIXE_API}"


def adresse_affichee(url_api: str) -> str:
    return url_api[: -len(SUFFIXE_API)] if url_api.endswith(SUFFIXE_API) else url_api


def verifier_reseau(url_api: str, quoi: str = "de votre Squash"):
    """Refuse une adresse qui mène à un réseau interne, sauf si le serveur l'autorise."""
    if reglages.squash_reseau_prive:
        return
    hote = urlsplit(url_api).hostname or ""
    try:
        infos = socket.getaddrinfo(hote, None)
    except socket.gaierror:
        raise ErreurConnexion(f"Adresse introuvable : « {hote} » n'existe pas ou n'est pas joignable depuis le service.")
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if not ip.is_global:
            raise ErreurConnexion(f"« {hote} » mène à un réseau interne, que le service ne contacte pas. "
                                  f"Indiquez l'adresse publique {quoi}.")


# ---------------------------------------------------------------- explications

def expliquer(erreurs, adresse: str = "", mode: str = "") -> str:
    """Traduit les erreurs techniques du module Squash en consignes compréhensibles."""
    texte = " ; ".join(str(e) for e in (erreurs or [])[:5])
    bas = texte.lower()
    detail = f" Détail : {texte[:300]}" if texte else ""
    ou = f" ({adresse})" if adresse else ""
    if "reseau-interne" in bas:
        message = (f"L'adresse de Squash{ou} mène à un réseau interne, que le service ne contacte pas. "
                   "Indiquez l'adresse publique de votre Squash.")
    elif "jwt" in bas:
        message = "Cette instance de Squash n'accepte pas les jetons d'API : choisissez « Identifiant et mot de passe »."
    elif any(m in bas for m in ("fetch failed", "econnrefused", "enotfound", "etimedout", "timeout", "certificate", "socket")):
        message = f"Squash injoignable{ou}. Vérifiez l'adresse et que votre Squash est accessible depuis Internet."
    elif "401" in bas or "unauthorized" in bas:
        message = ("Squash refuse ce jeton : il est incorrect, expiré ou révoqué. Créez-en un nouveau dans Squash "
                   "(Mon compte, Jetons d'API)." if mode == "jeton" else
                   "Squash refuse ce compte : identifiant ou mot de passe incorrect.")
    elif "403" in bas or "forbidden" in bas:
        message = ("Ce jeton n'a pas les droits nécessaires : il doit avoir le droit « Lecture et écriture » dans Squash, "
                   "et le compte doit pouvoir créer dans le projet visé." if mode == "jeton" else
                   "Ce compte n'a pas les droits nécessaires dans Squash (lecture et création dans le projet visé).")
    elif "404" in bas and ("fetch project:" in bas or "fetch project by name" in bas):
        message = "Projet Squash introuvable avec ce compte : vérifiez le projet choisi et les droits du compte."
    elif "404" in bas or "not valid json" in bas or "unexpected token" in bas or "<!doctype" in bas:
        message = (f"Aucune API Squash à cette adresse{ou}. Indiquez l'adresse que vous ouvrez dans le navigateur "
                   "pour aller sur Squash, souvent terminée par /squash.")
    else:
        return texte or "Squash a renvoyé une erreur."
    return message + detail


# ---------------------------------------------------------------- appels au module Squash

def environnement(cx: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(PREFIXES_RETIRES)}
    env["SQUASH_MCP_DIR"] = reglages.squash_mcp_dir
    env["SQUASH_TM_BASE_URL"] = cx["url"]
    if not reglages.squash_reseau_prive:
        env["SQUASH_RESEAU_PUBLIC_SEUL"] = "1"
    secret = dechiffrer(cx["secret"])
    if cx["mode"] == "jeton":
        env["SQUASH_TM_API_TOKEN"] = secret
    else:
        env["SQUASH_TM_USERNAME"] = cx["identifiant"] or ""
        env["SQUASH_TM_PASSWORD"] = secret
    return env


def appeler_module(cx: dict, *arguments, timeout=90, arret=None, delai_arret=120) -> dict:
    """Lance saas/publier_squash.mjs avec la connexion donnée ; renvoie son résultat JSON.

    arret : fonction appelée chaque seconde ; si elle renvoie vrai, le module est prié de s'arrêter
    avant la création suivante (fichier d'arrêt), puis arrêté de force après delai_arret secondes."""
    if not reglages.squash_mcp_dir:
        raise ErreurConnexion("Le module Squash n'est pas installé sur le serveur (SQUASH_MCP_DIR) : prévenez l'administrateur.")
    verifier_reseau(cx["url"])
    with tempfile.TemporaryDirectory(prefix="qaf-squash-") as tmp:
        fichier_arret = Path(tmp) / "arret"
        cmd = ["node", str(reglages.racine / "saas" / "publier_squash.mjs"), *map(str, arguments), "--arret", str(fichier_arret)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env=environnement(cx))
        debut, arret_demande = time.monotonic(), None
        while True:
            try:
                sortie, erreurs = p.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                maintenant_ = time.monotonic()
                if arret_demande is None and arret is not None and arret():
                    arret_demande = maintenant_
                    fichier_arret.touch()
                force = arret_demande is not None and maintenant_ - arret_demande > delai_arret
                if force or maintenant_ - debut > timeout:
                    p.kill()
                    p.communicate()
                    if force:
                        return {"termine": False, "arrete": True, "force": True, "erreurs": []}
                    raise ErreurConnexion(f"Squash ne répond pas ({adresse_affichee(cx['url'])}) : délai dépassé.")
    try:
        return json.loads(sortie)
    except json.JSONDecodeError:
        raise ErreurConnexion(f"Réponse illisible du module Squash : {(erreurs or sortie)[:300]}")


# ---------------------------------------------------------------- connexion de l'utilisateur

def lire(base, utilisateur_id):
    return base.un("SELECT * FROM connexions_squash WHERE utilisateur_id = ?", (utilisateur_id,))


def resume(cx):
    """Ce que les pages peuvent afficher (jamais le secret)."""
    if not cx:
        return None
    return {"adresse": adresse_affichee(cx["url"]), "mode": cx["mode"], "mode_libelle": MODES.get(cx["mode"], cx["mode"]),
            "identifiant": cx["identifiant"] or "", "verifiee_le": (cx["verifiee_le"] or "")[:16].replace("T", " à "),
            "projets": cx["projets_visibles"]}


def enregistrer(base, utilisateur_id, adresse: str, mode: str, identifiant: str, secret: str) -> dict:
    """Teste la connexion puis l'enregistre. Un secret laissé vide reprend celui qui est enregistré,
    seulement si l'adresse, le mode et l'identifiant n'ont pas changé (on n'envoie jamais un
    mot de passe enregistré vers une autre adresse)."""
    if mode not in MODES:
        raise ErreurConnexion("Choisissez comment se connecter : identifiant et mot de passe, ou jeton d'API.")
    url = normaliser_adresse(adresse)
    identifiant = (identifiant or "").strip()[:200] if mode == "compte" else ""
    if mode == "compte" and not identifiant:
        raise ErreurConnexion("Indiquez l'identifiant du compte Squash.")
    secret = (secret or "").strip()
    if len(secret) > 4000:
        raise ErreurConnexion("Secret trop long.")
    ancien = lire(base, utilisateur_id)
    if not secret:
        if ancien and (ancien["url"], ancien["mode"], ancien["identifiant"] or "") == (url, mode, identifiant):
            secret = dechiffrer(ancien["secret"])
        else:
            raise ErreurConnexion("Saisissez le mot de passe du compte Squash." if mode == "compte" else "Collez le jeton d'API Squash.")
    cx = {"url": url, "mode": mode, "identifiant": identifiant, "secret": chiffrer(secret)}
    res = appeler_module(cx, "--tester", timeout=45)
    if res.get("erreurs"):
        raise ErreurConnexion(expliquer(res["erreurs"], adresse_affichee(url), mode))
    cx.update(utilisateur_id=utilisateur_id, verifiee_le=maintenant(), projets_visibles=int(res.get("projets_visibles") or 0))
    base.x("INSERT INTO connexions_squash (utilisateur_id, url, mode, identifiant, secret, verifiee_le, projets_visibles, maj_le) "
           "VALUES (:utilisateur_id, :url, :mode, :identifiant, :secret, :verifiee_le, :projets_visibles, :verifiee_le) "
           "ON CONFLICT(utilisateur_id) DO UPDATE SET url = excluded.url, mode = excluded.mode, identifiant = excluded.identifiant, "
           "secret = excluded.secret, verifiee_le = excluded.verifiee_le, projets_visibles = excluded.projets_visibles, "
           "maj_le = excluded.maj_le", cx)
    return cx


def supprimer(base, utilisateur_id):
    base.x("DELETE FROM connexions_squash WHERE utilisateur_id = ?", (utilisateur_id,))
