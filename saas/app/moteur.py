# -*- coding: utf-8 -*-
"""Pilotage d'OpenCode en mode serveur (`opencode serve`) pour les étapes qui demandent l'IA.

Une tâche = une session OpenCode dans laquelle on lance une commande du dépôt (/analyser,
/corriger…). Pendant qu'elle tourne, on relève :
- les étapes (outils appelés, texte produit) pour les afficher en direct ;
- les demandes de confirmation (permission) et les questions de l'agent, que l'application
  présente au testeur sous forme de boutons ;
- le coût et les jetons consommés, pour suivre la facture OpenRouter.
"""
import threading
import time

import httpx

from .config import reglages


class ErreurMoteur(Exception):
    pass


def expliquer_erreur_modele(erreur: dict) -> str:
    """Traduit une erreur du fournisseur d'IA en consigne compréhensible."""
    nom = erreur.get("name", "Erreur")
    data = erreur.get("data") or {}
    detail = str(data.get("message") or "")
    bas = (nom + " " + detail).lower()
    statut = data.get("statusCode")
    if nom == "ProviderAuthError" or statut in (401, 403) and "proxy" not in bas or "api key" in bas or "unauthorized" in bas:
        texte = "Le fournisseur d'IA refuse la clé : vérifier la clé d'API (Paramètres > Modèles d'IA) ou le modèle choisi."
    elif statut == 402 or "credit" in bas or "insufficient" in bas:
        texte = "Crédit épuisé chez le fournisseur d'IA (ou plafond mensuel atteint) : recharger ou relever le plafond."
    elif statut == 429 or "rate limit" in bas or "too many" in bas:
        texte = ("Limite d'utilisation du modèle atteinte (fréquent avec les modèles gratuits) : réessayer plus tard, changer "
                 "de modèle ou ajouter des modèles de secours (Paramètres > Modèles d'IA).")
    elif coupure_reseau(erreur):
        texte = ("La connexion au fournisseur d'IA a été coupée à plusieurs reprises (réseau instable, proxy ou pare-feu) : "
                 "relancer la tâche ; si cela se répète, vérifier l'accès Internet du serveur.")
    elif "proxy" in bas or "econnrefused" in bas or "enotfound" in bas or "fetch failed" in bas or "network" in bas or "timeout" in bas:
        texte = "L'assistant ne parvient pas à joindre le fournisseur d'IA (réseau, proxy ou pare-feu du serveur)."
    elif nom == "ContextOverflowError":
        texte = "Le cahier des charges est trop long pour ce modèle : choisir un modèle à plus grande capacité ou découper le document."
    elif nom == "MessageAbortedError":
        texte = "Analyse arrêtée."
    else:
        texte = "L'assistant a rencontré une erreur."
    return f"{texte} Détail : {nom} {detail}".strip()


MOTS_COUPURE = ("econnreset", "socket connection was closed", "socket hang up", "cannot connect to api", "etimedout",
                "epipe", "connection reset", "other side closed", "terminated", "und_err")
REPRISES_MAX = 3
MESSAGE_REPRISE = ("La connexion au modèle a été coupée pendant ton travail. Reprends exactement là où tu t'es arrêté, "
                   "sans refaire ce qui est déjà écrit sur le disque, et termine la tâche demandée.")


MOTS_LIMITE = ("rate limit", "rate_limit", "ratelimit", "quota", "freeusagelimit", "usage limit", "limit exceeded",
               "too many requests", "resource_exhausted", "resource exhausted", "insufficient", "credits", "credit balance",
               "payment required", "billing", "aucune clé d'api")
MESSAGE_SUITE = ("Le modèle précédent a atteint sa limite d'utilisation. Poursuis la tâche demandée là où elle en est : "
                 "regarde ce qui est déjà écrit sur le disque, ne le refais pas, et termine le travail.")


def limite_atteinte(erreur: dict) -> bool:
    """Le modèle ne peut plus servir pour l'instant : quota ou crédit épuisé, trop de requêtes, clé absente ou refusée.
    La tâche peut alors continuer avec le modèle de secours suivant."""
    data = erreur.get("data") or {}
    if erreur.get("name") == "ProviderAuthError":
        return True
    if data.get("statusCode") in (401, 402, 403, 429):
        return True
    bas = (str(erreur.get("name", "")) + " " + str(data.get("message") or "") + " " + str(data.get("responseBody") or "")).lower()
    return any(m in bas for m in MOTS_LIMITE)


def coupure_reseau(erreur: dict) -> bool:
    """Erreur passagère de connexion au fournisseur d'IA (la session peut reprendre là où elle s'est arrêtée)."""
    data = erreur.get("data") or {}
    bas = (str(erreur.get("name", "")) + " " + str(data.get("message") or "")).lower()
    if erreur.get("name") in ("ProviderAuthError", "ContextOverflowError", "MessageAbortedError"):
        return False
    return any(m in bas for m in MOTS_COUPURE) or data.get("statusCode") in (502, 503, 504)


class Moteur:
    def __init__(self):
        self._client = None
        self.sessions_essai = {}   # session d'essai d'un modèle -> utilisateur (clé personnelle)
        self._sessions = {}        # cache session -> utilisateur (sessions filles comprises)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            auth = (reglages.opencode_utilisateur, reglages.opencode_mot_de_passe) if reglages.opencode_mot_de_passe else None
            # Moteur local : ne pas passer par le proxy du système (Windows l'applique aussi à 127.0.0.1).
            local = httpx.URL(reglages.opencode_url).host in ("127.0.0.1", "localhost", "::1")
            self._client = httpx.Client(base_url=reglages.opencode_url, auth=auth, trust_env=not local,
                                        params={"directory": str(reglages.racine)}, timeout=30)
        return self._client

    def disponible(self) -> tuple:
        try:
            # Le premier appel prépare le dossier de travail d'OpenCode : il peut prendre plusieurs secondes.
            r = self.client.get("/session/status", timeout=60)
        except httpx.HTTPError as e:
            return False, f"moteur OpenCode injoignable ({reglages.opencode_url}) : {e.__class__.__name__} {e}".strip()
        if r.status_code == 401:
            return False, "mot de passe du moteur refusé (OPENCODE_SERVER_PASSWORD)"
        if r.status_code >= 400:
            return False, f"le moteur OpenCode répond HTTP {r.status_code} : {r.text[:300]}"
        return True, ""

    # ---------------------------------------------------------------- exécution

    # ---------------------------------------------------------------- navigateur d'une tâche

    def ajouter_navigateur(self, nom: str, configuration: dict):
        """Ajoute au moteur, pour une tâche, un serveur MCP (navigateur Playwright) et le démarre."""
        r = self.client.post("/mcp", json={"name": nom, "config": configuration}, timeout=120)
        if r.status_code >= 400:
            raise ErreurMoteur(f"Le navigateur de test n'a pas pu démarrer (HTTP {r.status_code}) : {r.text[:300]}")
        etat = (r.json() or {}).get(nom) or {}
        if etat.get("status") == "failed":
            raise ErreurMoteur(f"Le navigateur de test n'a pas pu démarrer : {etat.get('error') or 'erreur inconnue'}")

    def retirer_navigateur(self, nom: str):
        try:
            self.client.post(f"/mcp/{nom}/disconnect", timeout=30)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def texte_commande(commande: str, arguments: str) -> str:
        """Texte d'une commande du dépôt (.opencode/commands/<commande>.md), comme OpenCode le construit."""
        import re
        f = reglages.racine / ".opencode" / "commands" / f"{commande}.md"
        if not f.exists():
            raise ErreurMoteur(f"Commande /{commande} introuvable dans le dépôt.")
        corps = re.sub(r"^---\n.*?\n---\n", "", f.read_text(encoding="utf-8"), count=1, flags=re.S)
        return corps.replace("$ARGUMENTS", arguments).strip()

    def modeles_disponibles(self) -> dict:
        """{fournisseur: [modèles]} connus du moteur (suggestions de la page Modèles d'IA) ; {} s'il ne répond pas."""
        try:
            d = self.client.get("/config/providers", timeout=15).json()
        except Exception:  # noqa: BLE001
            return {}
        return {p["id"]: sorted((p.get("models") or {}).keys()) for p in d.get("providers") or [] if p.get("id")}

    def utilisateur_de_session(self, base, sid: str, profondeur: int = 0):
        """Utilisateur pour lequel le moteur appelle le fournisseur (clé personnelle) : celui qui a lancé la tâche de la
        session, ou de sa session mère (sous-agent), ou l'auteur d'un essai de modèle. None si inconnu."""
        if not sid:
            return None
        if sid in self.sessions_essai:
            return self.sessions_essai[sid]
        if sid in self._sessions:
            return self._sessions[sid]
        r = base.un("SELECT cree_par FROM taches WHERE session_id = ?", (sid,))
        uid = r["cree_par"] if r else None
        if not r and profondeur < 3:
            try:
                parent = (self.client.get(f"/session/{sid}", timeout=10).json() or {}).get("parentID")
            except Exception:  # noqa: BLE001
                parent = None
            uid = self.utilisateur_de_session(base, parent, profondeur + 1) if parent else None
        if r or uid:
            if len(self._sessions) > 5000:
                self._sessions.clear()
            self._sessions[sid] = uid
        return uid

    def essayer_modele(self, modele: str, uid=None) -> tuple:
        """Courte demande au modèle, sans outil, à travers le moteur : (réussi, explication).
        uid : utilisateur dont la clé personnelle est essayée (sinon clé de l'entreprise ou du serveur)."""
        fournisseur, _, nom = modele.partition("/")
        try:
            s = self.client.post("/session", json={"title": f"Essai du modèle {modele}"[:80]})
            s.raise_for_status()
            sid = s.json()["id"]
            self.sessions_essai[sid] = uid
            r = self.client.post(f"/session/{sid}/message", timeout=120, json={
                "parts": [{"type": "text", "text": "Réponds uniquement : OK"}],
                "model": {"providerID": fournisseur, "modelID": nom}, "tools": {"*": False}})
        except httpx.HTTPError as e:
            return False, f"moteur injoignable ({e.__class__.__name__})"
        if r.status_code >= 400:
            texte = r.text[:300]
            if "ModelNotFound" in texte or "not found" in texte.lower():
                return False, f"modèle inconnu du moteur ({modele}) : vérifier son identifiant"
            return False, f"le moteur refuse la demande (HTTP {r.status_code}) : {texte}"
        try:
            d = r.json()
        except ValueError:
            return False, "réponse illisible du moteur"
        erreur = (d.get("info") or {}).get("error")
        if erreur:
            return False, expliquer_erreur_modele(erreur)
        if not any(p.get("type") == "text" and (p.get("text") or "").strip() for p in d.get("parts") or []):
            return False, "le modèle n'a rien répondu"
        return True, ""

    def executer(self, base, tid, commande, arguments, outils=None, modele=None, secours=None):
        """Lance la commande dans une nouvelle session et suit son déroulement jusqu'à la fin.

        outils : si fourni, la commande est envoyée comme message avec ces outils activés ou coupés
        (ex. seul le navigateur de la tâche) ; sinon par l'API des commandes d'OpenCode.
        modele : modèle de la tâche (Paramètres > Modèles d'IA) ; à défaut celui du serveur (QAF_MODELE).
        secours : modèles essayés dans l'ordre si le modèle atteint sa limite ; la session continue avec le suivant."""
        modele_complet = modele or reglages.modele
        restants = [m for m in (secours or []) if m and m != modele_complet]
        if not modele_complet:
            raise ErreurMoteur("Aucun modèle configuré (Paramètres > Modèles d'IA, ou variable QAF_MODELE).")
        s = self.client.post("/session", json={"title": f"{commande} {arguments}"[:80] + f" — tâche {tid}"})
        s.raise_for_status()
        sid = s.json()["id"]
        base.maj_tache(tid, session_id=sid)
        base.ajouter_journal(tid, f"Session OpenCode {sid} ouverte, modèle {modele_complet}.")

        if outils is None:
            chemin, corps = f"/session/{sid}/command", {"command": commande, "arguments": arguments, "model": modele_complet}
        else:
            fournisseur, _, modele = modele_complet.partition("/")
            chemin, corps = f"/session/{sid}/message", {
                "parts": [{"type": "text", "text": self.texte_commande(commande, arguments)}],
                "model": {"providerID": fournisseur, "modelID": modele}, "tools": outils}

        debut = time.time()
        reprises = 0
        courant = modele_complet
        while True:
            retour = {}

            def lancer(chemin=chemin, corps=corps):
                try:
                    retour["r"] = self.client.post(chemin, json=corps, timeout=reglages.duree_max_tache_min * 60)
                except Exception as e:  # noqa: BLE001
                    retour["e"] = e

            fil = threading.Thread(target=lancer, daemon=True)
            fil.start()
            while fil.is_alive():
                fil.join(reglages.intervalle_suivi_s)
                self._relever(base, tid, sid, courant)
                t = base.tache(tid)
                if t["annulation"]:
                    self.client.post(f"/session/{sid}/abort")
                    base.ajouter_journal(tid, "Arrêt demandé : session interrompue.")
                    fil.join(30)
                    return self._relever(base, tid, sid, courant)
                if time.time() - debut > reglages.duree_max_tache_min * 60:
                    self.client.post(f"/session/{sid}/abort")
                    raise ErreurMoteur(f"Durée maximale dépassée ({reglages.duree_max_tache_min} min).")
            bilan = self._relever(base, tid, sid, courant)
            if "e" in retour:
                raise ErreurMoteur(f"Échec de l'appel au moteur : {retour['e']}")
            r = retour.get("r")
            if r is None:
                return bilan
            if r.status_code >= 400:
                raise ErreurMoteur(f"Le moteur a refusé la commande (HTTP {r.status_code}) : {r.text[:300]}")
            erreur = (r.json().get("info") or {}).get("error")
            if not erreur:
                return bilan
            jamais_repondu = coupure_reseau(erreur) and not r.json().get("parts")
            if restants and (limite_atteinte(erreur) or jamais_repondu):
                # Limite du modèle atteinte : la même session continue avec le modèle de secours suivant.
                suivant = restants.pop(0)
                detail = ((erreur.get("data") or {}).get("message") or erreur.get("name") or "")[:160]
                base.ajouter_journal(tid, f"Limite atteinte avec {courant} ({detail}) : la tâche continue avec {suivant}.")
                courant, reprises = suivant, 0
                if base.tache(tid)["annulation"]:
                    return self._relever(base, tid, sid, courant)
                fournisseur, _, nom = courant.partition("/")
                chemin = f"/session/{sid}/message"
                corps = {"parts": [{"type": "text", "text": MESSAGE_SUITE}], "model": {"providerID": fournisseur, "modelID": nom}}
                if outils is not None:
                    corps["tools"] = outils
                continue
            if not coupure_reseau(erreur) or reprises >= REPRISES_MAX:
                raise ErreurMoteur(expliquer_erreur_modele(erreur))
            if not r.json().get("parts"):
                # OpenCode a déjà réessayé plusieurs fois sans obtenir un seul mot du modèle : ce n'est pas une coupure
                # passagère pendant le travail, le fournisseur refuse ou ne répond pas (souvent le quota gratuit épuisé).
                raise ErreurMoteur(
                    "Le modèle n'a jamais répondu : le fournisseur d'IA ferme la connexion dès la demande. Avec un modèle "
                    "gratuit (opencode/…-free), c'est en général la limite d'utilisation gratuite atteinte pour cette adresse "
                    "Internet : réessayer plus tard, ajouter des modèles de secours ou choisir un modèle avec une clé "
                    "(Paramètres > Modèles d'IA). Sinon, vérifier l'accès "
                    f"Internet du serveur. Détail : {(erreur.get('data') or {}).get('message', '')[:200]}")
            # Coupure passagère : la session garde tout son contexte, on la relance là où elle s'est arrêtée.
            reprises += 1
            base.ajouter_journal(tid, f"Connexion au modèle coupée ({(erreur.get('data') or {}).get('message', '')[:120]}) : "
                                      f"reprise {reprises} sur {REPRISES_MAX}.")
            time.sleep(min(30, 5 * reprises * reglages.intervalle_suivi_s))
            if base.tache(tid)["annulation"]:
                return self._relever(base, tid, sid, courant)
            fournisseur, _, nom = courant.partition("/")
            chemin = f"/session/{sid}/message"
            corps = {"parts": [{"type": "text", "text": MESSAGE_REPRISE}], "model": {"providerID": fournisseur, "modelID": nom}}
            if outils is not None:
                corps["tools"] = outils

    def _relever(self, base, tid, sid, modele=None) -> dict:
        """Étapes, compte rendu, coût ; demandes de confirmation et questions en attente."""
        try:
            msgs = self.client.get(f"/session/{sid}/message").json()
        except Exception:  # noqa: BLE001
            return {}
        etapes, textes, cout, jetons = [], [], 0.0, {"entree": 0, "sortie": 0}
        for m in msgs:
            info = m.get("info") or {}
            if info.get("role") != "assistant":
                continue
            cout += float(info.get("cost") or 0)
            tk = info.get("tokens") or {}
            jetons["entree"] += int(tk.get("input") or 0) + int((tk.get("cache") or {}).get("read") or 0)
            jetons["sortie"] += int(tk.get("output") or 0) + int(tk.get("reasoning") or 0)
            for p in m.get("parts") or []:
                if p.get("type") == "tool":
                    st = p.get("state") or {}
                    entree = st.get("input") or {}
                    quoi = st.get("title") or entree.get("command") or entree.get("filePath") or entree.get("name") or ""
                    etapes.append({"outil": p.get("tool"), "quoi": str(quoi)[:240], "statut": st.get("status", "")})
                elif p.get("type") == "text" and (p.get("text") or "").strip():
                    textes.append(p["text"].strip())
        attente = self._traiter_automatiquement(base, tid, self._en_attente(sid))
        bilan = {"etapes": etapes[-200:], "compte_rendu": textes[-1] if textes else "", "cout_usd": round(cout, 4),
                 "jetons": jetons, "messages": len(msgs), **({"modele": modele} if modele else {})}
        t = base.tache(tid)
        statut = t["statut"]
        if statut in ("en_cours", "attente_confirmation"):
            statut = "attente_confirmation" if attente else "en_cours"
        base.maj_tache(tid, resultat=bilan, attente=attente or None, statut=statut)
        return bilan

    def _traiter_automatiquement(self, base, tid, attente) -> list:
        """Aucune demande n'est présentée au testeur : sur le serveur, ce qui est utile à l'analyse est
        autorisé d'avance (opencode.serveur.json) et le reste est refusé. Une demande qui arriverait
        quand même est refusée ici, l'agent continue sans, et le refus est noté dans le journal."""
        for a in attente or []:
            try:
                if a["genre"] == "permission":
                    self.repondre_permission(a["id"], False, "Action non autorisée sur le serveur : continuer sans elle. "
                                             "Les ambiguïtés vont dans ambiguites.md, pas en question.")
                    base.ajouter_journal(tid, f"Action refusée automatiquement : {a.get('permission')} {a.get('detail') or ''}".strip())
                else:
                    self.rejeter_question(a["id"])
                    base.ajouter_journal(tid, "Question de l'assistant ignorée : elle doit figurer dans ambiguites.md.")
            except Exception:  # noqa: BLE001
                pass
        return []

    def _en_attente(self, sid) -> list:
        res = []
        try:
            for p in self.client.get("/permission").json():
                if p.get("sessionID") == sid:
                    meta = p.get("metadata") or {}
                    res.append({"genre": "permission", "id": p["id"], "permission": p.get("permission"),
                                "detail": meta.get("command") or meta.get("filepath") or ", ".join(p.get("patterns") or [])})
            for q in self.client.get("/question").json():
                if q.get("sessionID") == sid:
                    res.append({"genre": "question", "id": q["id"], "questions": q.get("questions") or []})
        except Exception:  # noqa: BLE001
            pass
        return res

    # ---------------------------------------------------------------- réponses

    def repondre_permission(self, demande_id, accepter: bool, message=""):
        r = self.client.post(f"/permission/{demande_id}/reply",
                             json={"reply": "once" if accepter else "reject", **({"message": message} if message else {})})
        if r.status_code >= 400:
            raise ErreurMoteur(f"Réponse refusée par le moteur : {r.text[:200]}")

    def repondre_question(self, demande_id, reponses: list):
        r = self.client.post(f"/question/{demande_id}/reply", json={"answers": reponses})
        if r.status_code >= 400:
            raise ErreurMoteur(f"Réponse refusée par le moteur : {r.text[:200]}")

    def rejeter_question(self, demande_id):
        self.client.post(f"/question/{demande_id}/reject")


moteur = Moteur()
