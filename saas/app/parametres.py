# -*- coding: utf-8 -*-
"""Paramètres de l'outil réglés dans l'application (page Paramètres) : modèles d'IA et modèles de documents.

Modèles d'IA
- Un modèle principal et, si besoin, un modèle par usage (analyse, tests, automatisation, manuel).
- Une chaîne de secours : quand le modèle atteint sa limite (quota gratuit, crédit épuisé, clé absente),
  la tâche continue avec le modèle suivant, dans la même session (rien n'est refait).
- Les modèles gratuits partagés (OpenRouter « :free », OpenCode Zen) ne sont utilisés que si l'administrateur
  les autorise : leurs fournisseurs peuvent se servir des données envoyées pour entraîner leurs modèles.
- Une clé d'API par fournisseur, chiffrée dans la base comme les secrets Squash, jamais réaffichée :
  clé personnelle de l'utilisateur qui lance la tâche, sinon clé de l'entreprise, sinon variable du serveur
  (OPENROUTER_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY…). Avec une clé gratuite par personne (Gemini, Groq…),
  les quotas gratuits s'additionnent.
- La clé ne quitte jamais l'application web : le moteur OpenCode appelle le fournisseur à travers le
  relais de l'application (app/relais_ia.py), qui ajoute la clé. L'agent ne peut donc pas la lire.

Modèles de documents
- Cahier de tests (.xlsx) et manuel utilisateur (.docx) de l'entreprise, déposés dans le dossier des données
  (QAF_DONNEES/modeles-documents) et analysés au dépôt (outils/cahier_modele.py, outils/manuel_modele.py).
- Sans modèle déposé, les modèles internes de QA Factory (templates/cahier, templates/manuel) sont utilisés.
"""
import json
import os
import re
from pathlib import Path

from . import connexions
from .config import reglages
from .db import maintenant

# Fournisseurs relayés (app/relais_ia.py) : adresse fixe, en-tête de la clé, variable du serveur.
# gratuit : ce que permet l'offre gratuite ; donnees : l'offre gratuite peut servir à entraîner leurs modèles.
FOURNISSEURS = {
    "google": {"libelle": "Google Gemini", "url": "https://generativelanguage.googleapis.com/v1beta", "env": "GEMINI_API_KEY",
               "entete": "x-goog-api-key", "lien": "https://aistudio.google.com/apikey",
               "aide": "Clé créée en une minute sur Google AI Studio, sans carte bancaire.",
               "gratuit": "Offre gratuite : modèles Flash, quelques centaines de requêtes par jour et par clé (une à deux analyses).",
               "donnees": True},
    "openrouter": {"libelle": "OpenRouter", "url": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY",
                   "entete": "authorization", "lien": "https://openrouter.ai/keys",
                   "aide": "Une seule clé donne accès aux modèles d'Anthropic, OpenAI, Google, DeepSeek…",
                   "gratuit": "Modèles « :free » : 50 requêtes par jour, 1 000 après un achat unique de 10 $ de crédits.",
                   "donnees": True},
    "groq": {"libelle": "Groq", "url": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY", "entete": "authorization",
             "lien": "https://console.groq.com/keys", "aide": "Très rapide ; clé gratuite sur console.groq.com.",
             "gratuit": "Offre gratuite : 1 000 requêtes mais environ 200 000 jetons par jour, trop peu pour une analyse complète.",
             "donnees": False},
    "cerebras": {"libelle": "Cerebras", "url": "https://api.cerebras.ai/v1", "env": "CEREBRAS_API_KEY", "entete": "authorization",
                 "lien": "https://cloud.cerebras.ai", "aide": "Clé sur cloud.cerebras.ai.",
                 "gratuit": "Offre d'essai dont les conditions changent souvent.", "donnees": False},
    "mistral": {"libelle": "Mistral", "url": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY", "entete": "authorization",
                "lien": "https://console.mistral.ai/api-keys", "aide": "Fournisseur européen ; clé sur console.mistral.ai.",
                "gratuit": "Offre « Experiment » gratuite, limites visibles dans la console.", "donnees": True},
    "deepseek": {"libelle": "DeepSeek", "url": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY", "entete": "authorization",
                 "lien": "https://platform.deepseek.com/api_keys",
                 "aide": "Payant à l'usage, parmi les moins chers ; clé sur platform.deepseek.com.", "gratuit": "", "donnees": False},
    "anthropic": {"libelle": "Anthropic", "url": "https://api.anthropic.com/v1", "env": "ANTHROPIC_API_KEY",
                  "entete": "x-api-key", "lien": "https://console.anthropic.com/settings/keys",
                  "aide": "Clé de la console Anthropic (payante, distincte de l'abonnement Claude).", "gratuit": "", "donnees": False},
    "openai": {"libelle": "OpenAI", "url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "entete": "authorization", "lien": "https://platform.openai.com/api-keys",
               "aide": "Clé de la plateforme OpenAI (payante).", "gratuit": "", "donnees": False},
}
# Sans clé : le service gratuit d'OpenCode (quota partagé par adresse Internet) et le faux modèle de démonstration.
SANS_CLE = ("opencode", "simulation")

# Liste déroulante de la page Modèles d'IA : modèles connus, capables d'utiliser des outils (indispensable à l'agent).
CATALOGUE = [
    ("Gratuits avec une clé gratuite", [
        ("google/gemini-3-flash-preview", "Gemini 3 Flash (Google) · recommandé en gratuit", True),
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash (Google)", True),
        ("google/gemini-flash-lite-latest", "Gemini Flash-Lite (Google) · quotas plus larges", True),
        ("groq/openai/gpt-oss-120b", "GPT-OSS 120B (Groq) · petites tâches", True),
        ("cerebras/gpt-oss-120b", "GPT-OSS 120B (Cerebras)", True),
        ("mistral/mistral-small-latest", "Mistral Small (Mistral)", True),
        ("openrouter/openrouter/free", "Meilleur modèle gratuit du moment (OpenRouter)", True),
        ("openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra (OpenRouter, gratuit)", True),
    ]),
    ("Gratuits sans clé (OpenCode, quota partagé)", [
        ("opencode/deepseek-v4.1-flash-free", "DeepSeek V4.1 Flash (OpenCode)", True),
        ("opencode/glm-5.3-flash-free", "GLM-5.3 Flash (OpenCode)", True),
        ("opencode/big-pickle", "Big Pickle (OpenCode)", True),
    ]),
    ("Payants, peu chers", [
        ("deepseek/deepseek-flash", "DeepSeek V4.1 Flash (DeepSeek)", False),
        ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro (DeepSeek)", False),
        ("anthropic/claude-haiku-5-5", "Claude Haiku 5.5 (Anthropic)", False),
        ("openrouter/anthropic/claude-haiku-5.5", "Claude Haiku 5.5 (OpenRouter)", False),
        ("openrouter/z-ai/glm-5.3", "GLM-5.3 (OpenRouter)", False),
        ("openai/gpt-5.4-mini", "GPT-5.4 mini (OpenAI)", False),
    ]),
    ("Payants, les plus capables", [
        ("anthropic/claude-sonnet-5-5", "Claude Sonnet 5.5 (Anthropic)", False),
        ("openrouter/anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5 (OpenRouter)", False),
        ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro (Google)", False),
        ("mistral/mistral-large-latest", "Mistral Large (Mistral)", False),
        ("openai/gpt-5", "GPT-5 (OpenAI)", False),
    ]),
]
SECOURS_MAX = 5
USAGES = {
    "analyse": "Analyse du cahier des charges et corrections",
    "tests": "Tests de l'application",
    "automatisation": "Écriture des scripts Playwright",
    "documents": "Rédaction du manuel utilisateur",
}
USAGE_DES_TACHES = {"analyser": "analyse", "corriger": "analyse", "tester": "tests", "automatiser": "automatisation",
                    "manuel": "documents"}
RE_MODELE = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._:/@+-]{1,120}$")
AUTRE = "__autre__"

DOCUMENTS = {
    "cahier": {"libelle": "Cahier de tests", "extension": ".xlsx", "fichier": "cahier.xlsx",
               "interne": "Modèle interne QA Factory (templates/cahier/modele_cahier.xlsx)"},
    "manuel": {"libelle": "Manuel utilisateur", "extension": ".docx", "fichier": "manuel.docx",
               "interne": "Modèle interne QA Factory (templates/manuel/modele_manuel.docx)"},
}


class ErreurParametres(Exception):
    pass


# ---------------------------------------------------------------- stockage

def lire(base, cle: str, defaut=None):
    r = base.un("SELECT valeur FROM reglages_app WHERE cle = ?", (cle,))
    if not r:
        return defaut
    try:
        return json.loads(r["valeur"])
    except ValueError:
        return defaut


def ecrire(base, cle: str, valeur, uid=None):
    base.x("INSERT INTO reglages_app (cle, valeur, maj_par, maj_le) VALUES (?,?,?,?) "
           "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur, maj_par = excluded.maj_par, maj_le = excluded.maj_le",
           (cle, json.dumps(valeur, ensure_ascii=False), uid, maintenant()))


def effacer(base, cle: str):
    base.x("DELETE FROM reglages_app WHERE cle = ?", (cle,))


# ---------------------------------------------------------------- modèles d'IA

def config_ia(base) -> dict:
    c = lire(base, "ia", {}) or {}
    return {"principal": c.get("principal") or "", "usages": {k: (c.get("usages") or {}).get(k) or "" for k in USAGES},
            "secours": [m for m in c.get("secours") or [] if m][:SECOURS_MAX], "gratuits": bool(c.get("gratuits")),
            "maj_le": c.get("maj_le") or "", "maj_par": c.get("maj_par") or ""}


def est_gratuit_partage(modele: str) -> bool:
    """Modèle gratuit dont le fournisseur peut garder les données : OpenRouter « :free », OpenCode Zen."""
    m = (modele or "").lower()
    return m.startswith("opencode/") or m.endswith(":free") or m == "openrouter/openrouter/free"


def utilisable(base, modele: str, uid=None) -> bool:
    """Le modèle peut-il servir : fournisseur sans clé ou avec une clé (personnelle, entreprise, serveur),
    et, pour un modèle gratuit partagé, autorisé par l'administrateur."""
    f = (modele or "").split("/", 1)[0]
    if est_gratuit_partage(modele) and not config_ia(base)["gratuits"]:
        return False
    return f in SANS_CLE or bool(cle_pour(base, f, uid))


def secours_pour(base, type_tache: str = "", uid=None) -> list:
    """Modèles de secours d'une tâche, dans l'ordre, sans le modèle de la tâche ni ceux qui ne peuvent pas servir."""
    vus, res = {modele_pour(base, type_tache)}, []
    for m in config_ia(base)["secours"]:
        if m not in vus and utilisable(base, m, uid):
            vus.add(m)
            res.append(m)
    return res


def modele_pour(base, type_tache: str = "") -> str:
    """Modèle d'une tâche : celui de son usage, sinon le principal, sinon celui du serveur (QAF_MODELE)."""
    c = config_ia(base)
    usage = USAGE_DES_TACHES.get(type_tache)
    return (c["usages"].get(usage) if usage else "") or c["principal"] or reglages.modele


def cle_enregistree(base, fournisseur: str) -> str:
    r = lire(base, f"cle_ia:{fournisseur}")
    if not r or not r.get("secret"):
        return ""
    try:
        return connexions.dechiffrer(r["secret"])
    except connexions.ErreurConnexion:
        return ""


def cle_personnelle(base, uid, fournisseur: str) -> str:
    if not uid:
        return ""
    r = lire(base, f"cle_ia_u:{uid}:{fournisseur}")
    if not r or not r.get("secret"):
        return ""
    try:
        return connexions.dechiffrer(r["secret"])
    except connexions.ErreurConnexion:
        return ""


def cle_pour(base, fournisseur: str, uid=None) -> str:
    """Clé d'API utilisée par le relais : celle de l'utilisateur qui a lancé la tâche, sinon celle de l'entreprise,
    sinon celle du serveur."""
    if fournisseur not in FOURNISSEURS:
        return ""
    return (cle_personnelle(base, uid, fournisseur) or cle_enregistree(base, fournisseur)
            or os.environ.get(FOURNISSEURS[fournisseur]["env"], "").strip())


def _controler_cle(f: str, cle: str) -> str:
    cle = (cle or "").strip()
    if cle and (len(cle) > 400 or any(ch.isspace() for ch in cle)):
        raise ErreurParametres(f"Clé {FOURNISSEURS[f]['libelle']} invalide (espaces ou longueur).")
    return cle


def enregistrer_cles_personnelles(base, utilisateur: dict, cles: dict, retirer: list) -> dict:
    """Clés personnelles d'un utilisateur ; renvoie l'état précédent (retour en arrière si l'essai échoue)."""
    uid = utilisateur["id"]
    avant = {f"cle_ia_u:{uid}:{f}": lire(base, f"cle_ia_u:{uid}:{f}") for f in FOURNISSEURS}
    for f, cle in (cles or {}).items():
        if f not in FOURNISSEURS:
            continue
        cle = _controler_cle(f, cle)
        if cle:
            ecrire(base, f"cle_ia_u:{uid}:{f}", {"secret": connexions.chiffrer(cle), "fin": cle[-4:], "maj_le": maintenant()}, uid)
    for f in retirer or []:
        if f in FOURNISSEURS:
            effacer(base, f"cle_ia_u:{uid}:{f}")
    return avant


def resume_cles_personnelles(base, uid) -> dict:
    res = {}
    for f in FOURNISSEURS:
        r = lire(base, f"cle_ia_u:{uid}:{f}") or {}
        res[f] = {"enregistree": bool(r.get("secret")), "fin": r.get("fin") or "", "maj_le": r.get("maj_le") or ""}
    return res


def choisir(form, nom: str) -> str:
    """Valeur d'une liste déroulante de modèles : le choix, ou le champ « autre modèle » s'il est choisi."""
    v = str(form.get(nom) or "").strip()
    return str(form.get(nom + "_autre") or "").strip() if v == AUTRE else v


def catalogue_affiche(connus: dict) -> list:
    """Groupes de la liste déroulante ; un modèle absent du catalogue du moteur est signalé."""
    res = []
    for groupe, modeles in CATALOGUE:
        lignes = []
        for m, libelle, gratuit in modeles:
            f, _, nom = m.partition("/")
            absent = bool(connus) and f in connus and nom not in connus[f]
            lignes.append({"modele": m, "libelle": libelle + (" · introuvable dans le moteur" if absent else ""),
                           "gratuit": gratuit, "partage": est_gratuit_partage(m)})
        res.append((groupe, lignes))
    return res


def controler_modele(m: str) -> str:
    m = (m or "").strip()
    if not m:
        return ""
    if not RE_MODELE.match(m):
        raise ErreurParametres(f"« {m[:80]} » : un modèle s'écrit fournisseur/modèle, ex. openrouter/anthropic/claude-sonnet-5.5.")
    f = m.split("/", 1)[0]
    if f not in FOURNISSEURS and f not in SANS_CLE:
        raise ErreurParametres(f"Fournisseur « {f} » non pris en charge : " + ", ".join(FOURNISSEURS) + ".")
    return m


def enregistrer_ia(base, principal: str, usages: dict, cles: dict, retirer: list, utilisateur: dict,
                   secours: list = None, gratuits: bool = False) -> dict:
    """Enregistre ; renvoie l'état précédent (pour revenir en arrière si l'essai échoue)."""
    avant = {"ia": lire(base, "ia"), **{f"cle_ia:{f}": lire(base, f"cle_ia:{f}") for f in FOURNISSEURS}}
    chaine = []
    for m in secours or []:
        m = controler_modele(m)
        if m and m not in chaine:
            chaine.append(m)
    c = {"principal": controler_modele(principal), "usages": {k: controler_modele(usages.get(k, "")) for k in USAGES},
         "secours": chaine[:SECOURS_MAX], "gratuits": bool(gratuits), "maj_le": maintenant(), "maj_par": utilisateur.get("nom", "")}
    if not gratuits:
        partages = [m for m in [c["principal"], *c["usages"].values(), *chaine] if est_gratuit_partage(m)]
        if partages:
            raise ErreurParametres(f"« {partages[0]} » est un modèle gratuit dont le fournisseur peut garder les données : "
                                   "cocher d'abord « J'accepte que ce service gratuit puisse réutiliser les documents envoyés ».")
    for f, cle in (cles or {}).items():
        if f not in FOURNISSEURS:
            continue
        cle = _controler_cle(f, cle)
        if not cle:
            continue
        ecrire(base, f"cle_ia:{f}", {"secret": connexions.chiffrer(cle), "fin": cle[-4:], "maj_le": maintenant(),
                                     "maj_par": utilisateur.get("nom", "")}, utilisateur.get("id"))
    for f in retirer or []:
        if f in FOURNISSEURS:
            effacer(base, f"cle_ia:{f}")
    ecrire(base, "ia", c, utilisateur.get("id"))
    return avant


def restaurer(base, avant: dict):
    for cle, valeur in avant.items():
        if valeur is None:
            effacer(base, cle)
        else:
            ecrire(base, cle, valeur)


def resume_ia(base, uid=None) -> dict:
    c = config_ia(base)
    cles = {}
    for f, info in FOURNISSEURS.items():
        r = lire(base, f"cle_ia:{f}") or {}
        cles[f] = {"enregistree": bool(r.get("secret")), "fin": r.get("fin") or "", "maj_le": r.get("maj_le") or "",
                   "serveur": bool(os.environ.get(info["env"], "").strip())}
    effectifs = {k: modele_pour(base, next(t for t, u in USAGE_DES_TACHES.items() if u == k)) for k in USAGES}
    return {**c, "cles": cles, "defaut": reglages.modele, "effectifs": effectifs,
            "inutilisables": sorted({m for m in [*effectifs.values(), *c["secours"]]
                                     if m and not m.startswith("simulation/") and not utilisable(base, m, uid)})}


def modeles_a_essayer(base) -> list:
    return sorted(({modele_pour(base, t) for t in USAGE_DES_TACHES} | set(config_ia(base)["secours"])) - {""})


# ---------------------------------------------------------------- modèles de documents

def dossier_modeles() -> Path:
    d = reglages.donnees / "modeles-documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def chemin_modele(type_: str):
    """Fichier du modèle de l'entreprise, ou None (modèle interne)."""
    info = DOCUMENTS.get(type_)
    if not info:
        return None
    f = dossier_modeles() / info["fichier"]
    return f if f.is_file() else None


def analyser_modele(type_: str, donnees: bytes) -> dict:
    if type_ == "cahier":
        import cahier_modele as m
    else:
        import manuel_modele as m
    try:
        return m.analyser(donnees)
    except m.ErreurModele as e:
        raise ErreurParametres(str(e))


def deposer_modele(base, type_: str, nom: str, donnees: bytes, utilisateur: dict) -> dict:
    info = DOCUMENTS.get(type_)
    if not info:
        raise ErreurParametres("Type de document inconnu.")
    nom = Path(nom or "").name[:150]
    if not nom.lower().endswith(info["extension"]):
        raise ErreurParametres(f"Le modèle de {info['libelle'].lower()} doit être un fichier {info['extension']}.")
    analyse = analyser_modele(type_, donnees)
    f = dossier_modeles() / info["fichier"]
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_bytes(donnees)
    os.replace(tmp, f)
    meta = {"nom": nom, "taille": len(donnees), "depose_le": maintenant(), "depose_par": utilisateur.get("nom", ""),
            "analyse": analyse}
    ecrire(base, f"modele:{type_}", meta, utilisateur.get("id"))
    return meta


def retirer_modele(base, type_: str):
    f = chemin_modele(type_)
    if f:
        f.unlink(missing_ok=True)
    effacer(base, f"modele:{type_}")


def resume_documents(base) -> dict:
    res = {}
    for t, info in DOCUMENTS.items():
        meta = lire(base, f"modele:{t}") if chemin_modele(t) else None
        res[t] = {**info, "modele": meta}
    return res
