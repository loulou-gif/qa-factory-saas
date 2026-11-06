# -*- coding: utf-8 -*-
"""Relais entre le moteur OpenCode et le fournisseur d'IA : la clé d'API reste dans l'application web.

OpenCode est configuré (saas/config_moteur.py) pour appeler <QAF_RELAIS_IA>/<fournisseur>/… avec un jeton
interne à la place de la clé. Le relais vérifie ce jeton, remplace l'en-tête d'authentification par la clé
enregistrée dans Paramètres > Modèles d'IA (sinon celle des variables du serveur), puis renvoie la réponse
du fournisseur au fil de l'eau (streaming).

- Jeton : QAF_JETON_RELAIS, ou à défaut dérivé de OPENCODE_SERVER_PASSWORD (connu des deux conteneurs).
- Seules les routes d'inférence sont relayées (pas de gestion de compte, de facturation ni de clés).
- Fournisseurs : ceux de app/parametres.py (Google, OpenRouter, Groq, Cerebras, Mistral, DeepSeek, Anthropic, OpenAI),
  adresses fixes.
- Clé : celle de l'utilisateur qui a lancé la tâche (retrouvé par l'en-tête x-opencode-session-id), sinon celle
  de l'entreprise, sinon celle du serveur (app/main.py).
"""
import hashlib
import hmac
import os

import httpx
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, StreamingResponse

from .parametres import FOURNISSEURS

CHEMINS = ("chat/completions", "completions", "responses", "messages", "models", "embeddings")
ENTETES_TRANSMISES = {"content-type", "accept", "user-agent", "anthropic-version", "anthropic-beta", "http-referer",
                      "x-title", "openai-beta", "x-stainless-arch", "x-stainless-lang", "x-stainless-os",
                      "x-stainless-package-version", "x-stainless-runtime", "x-stainless-runtime-version"}
CORPS_MAX = 30 * 1024 * 1024


def jeton_relais() -> str:
    j = os.environ.get("QAF_JETON_RELAIS", "").strip()
    if j:
        return j
    mdp = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not mdp:
        return ""
    return hmac.new(mdp.encode(), b"qaf-relais-ia", hashlib.sha256).hexdigest()


def _erreur(statut: int, message: str, fournisseur: str = ""):
    # Format compris par les SDK OpenAI et Anthropic : OpenCode affiche le message dans le journal de la tâche.
    corps = {"error": {"message": message, "type": "qaf_relais"}}
    if fournisseur == "anthropic":
        corps = {"type": "error", "error": {"type": "authentication_error" if statut == 401 else "api_error", "message": message}}
    return JSONResponse(corps, status_code=statut)


def jeton_recu(request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-api-key") or request.headers.get("x-goog-api-key") or "").strip()


async def relayer(request, fournisseur: str, chemin: str, cle: str):
    info = FOURNISSEURS.get(fournisseur)
    attendu = jeton_relais()
    if not info:
        return _erreur(404, "Fournisseur inconnu.")
    if not attendu or not hmac.compare_digest(jeton_recu(request), attendu):
        return _erreur(401, "Jeton du relais refusé.", fournisseur)
    chemin = chemin.strip("/")
    if not any(chemin == c or chemin.startswith(c + "/") for c in CHEMINS) or ".." in chemin:
        return _erreur(404, "Route non relayée.", fournisseur)
    if not cle:
        return _erreur(401, f"Aucune clé d'API {info['libelle']} : la renseigner dans Paramètres > Modèles d'IA "
                            f"(clé personnelle ou de l'entreprise), ou la variable {info['env']} du serveur.", fournisseur)
    corps = await request.body()
    if len(corps) > CORPS_MAX:
        return _erreur(413, "Requête trop volumineuse.", fournisseur)
    entetes = {k: v for k, v in request.headers.items() if k.lower() in ENTETES_TRANSMISES}
    entetes["accept-encoding"] = "identity"
    if info["entete"] != "authorization":
        entetes[info["entete"]] = cle
    else:
        entetes["authorization"] = f"Bearer {cle}"
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=900, write=120, pool=30), trust_env=True)
    try:
        req = client.build_request(request.method, f"{info['url']}/{chemin}", headers=entetes, content=corps,
                                   params=dict(request.query_params))
        r = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        return _erreur(502, f"{info['libelle']} injoignable depuis le serveur : {e.__class__.__name__}.", fournisseur)

    async def fermer():
        await r.aclose()
        await client.aclose()

    sortie = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "retry-after", "x-request-id", "request-id")}
    sortie["cache-control"] = "no-store"
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=sortie, background=BackgroundTask(fermer))
