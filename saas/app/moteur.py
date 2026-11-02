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
        texte = "Le fournisseur d'IA refuse la clé : vérifier OPENROUTER_API_KEY (ou le modèle choisi)."
    elif statut == 402 or "credit" in bas or "insufficient" in bas:
        texte = "Crédit épuisé chez le fournisseur d'IA (ou plafond mensuel atteint) : recharger ou relever le plafond."
    elif statut == 429 or "rate limit" in bas or "too many" in bas:
        texte = "Limite d'utilisation du modèle atteinte (fréquent avec les modèles gratuits) : réessayer plus tard ou changer de modèle."
    elif "proxy" in bas or "econnrefused" in bas or "enotfound" in bas or "fetch failed" in bas or "network" in bas or "timeout" in bas:
        texte = "L'assistant ne parvient pas à joindre le fournisseur d'IA (réseau, proxy ou pare-feu du serveur)."
    elif nom == "ContextOverflowError":
        texte = "Le cahier des charges est trop long pour ce modèle : choisir un modèle à plus grande capacité ou découper le document."
    elif nom == "MessageAbortedError":
        texte = "Analyse arrêtée."
    else:
        texte = "L'assistant a rencontré une erreur."
    return f"{texte} Détail : {nom} {detail}".strip()


class Moteur:
    def __init__(self):
        self._client = None

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

    def executer(self, base, tid, commande, arguments):
        """Lance la commande dans une nouvelle session et suit son déroulement jusqu'à la fin."""
        if not reglages.modele:
            raise ErreurMoteur("Aucun modèle configuré (variable QAF_MODELE).")
        s = self.client.post("/session", json={"title": f"{commande} {arguments}"[:80] + f" — tâche {tid}"})
        s.raise_for_status()
        sid = s.json()["id"]
        base.maj_tache(tid, session_id=sid)
        base.ajouter_journal(tid, f"Session OpenCode {sid} ouverte, modèle {reglages.modele}.")

        retour = {}

        def lancer():
            try:
                r = self.client.post(f"/session/{sid}/command",
                                     json={"command": commande, "arguments": arguments, "model": reglages.modele},
                                     timeout=reglages.duree_max_tache_min * 60)
                retour["r"] = r
            except Exception as e:  # noqa: BLE001
                retour["e"] = e

        fil = threading.Thread(target=lancer, daemon=True)
        fil.start()
        debut = time.time()
        while fil.is_alive():
            fil.join(reglages.intervalle_suivi_s)
            self._relever(base, tid, sid)
            t = base.tache(tid)
            if t["annulation"]:
                self.client.post(f"/session/{sid}/abort")
                base.ajouter_journal(tid, "Arrêt demandé : session interrompue.")
                fil.join(30)
                break
            if time.time() - debut > reglages.duree_max_tache_min * 60:
                self.client.post(f"/session/{sid}/abort")
                raise ErreurMoteur(f"Durée maximale dépassée ({reglages.duree_max_tache_min} min).")
        bilan = self._relever(base, tid, sid)
        if "e" in retour:
            raise ErreurMoteur(f"Échec de l'appel au moteur : {retour['e']}")
        r = retour.get("r")
        if r is None:
            return bilan
        if r.status_code >= 400:
            raise ErreurMoteur(f"Le moteur a refusé la commande (HTTP {r.status_code}) : {r.text[:300]}")
        erreur = (r.json().get("info") or {}).get("error")
        if erreur:
            raise ErreurMoteur(expliquer_erreur_modele(erreur))
        return bilan

    def _relever(self, base, tid, sid) -> dict:
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
                 "jetons": jetons, "messages": len(msgs)}
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
