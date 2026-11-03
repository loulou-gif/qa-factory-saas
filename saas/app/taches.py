# -*- coding: utf-8 -*-
"""File des tâches longues : analyse et corrections (IA), publication Squash, specs.

Une seule tâche active par projet (pas d'écritures concurrentes dans un même dossier) ;
un nombre limité de tâches en parallèle sur le serveur (QAF_TACHES_PARALLELES).
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import projets
from .config import reglages
from .db import STATUTS_ACTIFS, maintenant
from .moteur import ErreurMoteur, moteur

TYPES = {
    "analyser": "Analyse du cahier des charges",
    "corriger": "Correction demandée",
    "publier-simulation": "Simulation de publication Squash",
    "publier": "Publication dans Squash",
    "specs": "Specs d'automatisation",
}
STATUTS = {
    "en_attente": "En attente", "en_cours": "En cours", "attente_confirmation": "Confirmation demandée",
    "termine": "Terminée", "echec": "Échec", "annule": "Annulée", "interrompue": "Interrompue",
}


class ErreurTache(Exception):
    pass


def expliquer_erreur_squash(erreurs):
    """Traduit les erreurs techniques du module Squash en consignes compréhensibles."""
    texte = " ; ".join(str(e) for e in erreurs[:5])
    bas = texte.lower()
    if "fetch failed" in bas or "econnrefused" in bas or "enotfound" in bas or "timeout" in bas:
        return (f"Squash injoignable depuis le serveur ({reglages.squash_url or 'adresse non définie'}). "
                f"Vérifier l'adresse SQUASH_TM_BASE_URL et l'accès réseau du serveur à Squash. Détail : {texte}")
    if "401" in bas or "unauthorized" in bas:
        return f"Squash refuse les identifiants du serveur (SQUASH_TM_USERNAME / SQUASH_TM_PASSWORD ou jeton). Détail : {texte}"
    if "404" in bas and "projet" in bas:
        return f"Projet Squash introuvable : vérifier l'ID du projet dans la fiche et les droits du compte. Détail : {texte}"
    return texte


class Gestionnaire:
    def __init__(self):
        self.base = None
        self.pool = None

    def demarrer(self, base):
        self.base = base
        self.pool = ThreadPoolExecutor(max_workers=max(1, reglages.taches_paralleles), thread_name_prefix="tache")
        # Après un redémarrage du serveur, les tâches qui tournaient ne reprendront pas.
        for t in base.tous(f"SELECT id FROM taches WHERE statut IN ({','.join('?' * len(STATUTS_ACTIFS))})", STATUTS_ACTIFS):
            base.maj_tache(t["id"], statut="interrompue", fin=maintenant(), attente=None)
            base.ajouter_journal(t["id"], "Interrompue par un redémarrage du serveur.")

    def active(self, projet):
        return self.base.un(f"SELECT id, type FROM taches WHERE projet = ? AND statut IN ({','.join('?' * len(STATUTS_ACTIFS))}) "
                            "ORDER BY id DESC", (projet, *STATUTS_ACTIFS))

    def soumettre(self, projet, type_, utilisateur, parametres=None) -> int:
        if type_ not in TYPES:
            raise ErreurTache("Type de tâche inconnu.")
        a = self.active(projet)
        if a:
            raise ErreurTache(f"Une tâche est déjà en cours sur ce projet ({TYPES.get(a['type'], a['type'])}, n° {a['id']}). "
                              "Attendre sa fin ou l'arrêter.")
        cur = self.base.x("INSERT INTO taches (projet, type, statut, parametres, cree_par, cree_le) VALUES (?,?,?,?,?,?)",
                          (projet, type_, "en_attente", json.dumps(parametres or {}, ensure_ascii=False),
                           utilisateur["id"], maintenant()))
        tid = cur.lastrowid
        self.base.ajouter_journal(tid, f"{TYPES[type_]} demandée par {utilisateur['nom']}.")
        self.base.auditer(utilisateur["id"], projet, f"tache:{type_}", f"tâche {tid}")
        self.pool.submit(self._executer, tid)
        return tid

    def annuler(self, tid, utilisateur):
        t = self.base.tache(tid)
        if not t or t["statut"] not in STATUTS_ACTIFS:
            return
        self.base.maj_tache(tid, annulation=1)
        self.base.ajouter_journal(tid, f"Arrêt demandé par {utilisateur['nom']}.")
        if t["statut"] == "en_attente":
            self.base.maj_tache(tid, statut="annule", fin=maintenant())

    # ---------------------------------------------------------------- exécution

    def _executer(self, tid):
        t = self.base.tache(tid)
        if t["statut"] != "en_attente" or t["annulation"]:
            return
        self.base.maj_tache(tid, statut="en_cours", debut=maintenant())
        try:
            fonction = {"analyser": self._ia, "corriger": self._ia, "publier-simulation": self._publier,
                        "publier": self._publier, "specs": self._specs}[t["type"]]
            fonction(t)
            t = self.base.tache(tid)
            self.base.maj_tache(tid, statut="annule" if t["annulation"] else "termine", fin=maintenant(), attente=None)
            self.base.ajouter_journal(tid, "Arrêtée." if t["annulation"] else "Terminée.")
        except (ErreurMoteur, ErreurTache, projets.ErreurProjet) as e:
            self.base.maj_tache(tid, statut="echec", fin=maintenant(), attente=None)
            self.base.ajouter_journal(tid, f"Échec : {e}")
        except Exception as e:  # noqa: BLE001
            self.base.maj_tache(tid, statut="echec", fin=maintenant(), attente=None)
            self.base.ajouter_journal(tid, f"Erreur inattendue : {e.__class__.__name__} : {e}")

    def _ia(self, t):
        code = t["projet"]
        if t["type"] == "analyser":
            if projets.etat(code)["a_valider"]:
                raise ErreurTache("Une analyse existe déjà dans 02-a-valider : utiliser « Corriger ».")
            commande, arguments = "analyser", code
        else:
            demande = (t["parametres"].get("demande") or "").strip()
            if not demande:
                raise ErreurTache("Demande de correction vide.")
            # Les modifications éventuelles de l'Excel ou du Word sont importées avant la demande écrite.
            s = projets.synchroniser(code)
            if s["conflit"]:
                raise ErreurTache("L'Excel et le Word ont été modifiés différemment : choisir lequel garder "
                                  "(page du projet) avant d'envoyer une demande.")
            commande, arguments = "corriger", f"{code} {demande}"
        bilan = moteur.executer(self.base, t["id"], commande, arguments)
        if t["type"] == "analyser" and not self.base.tache(t["id"])["annulation"] \
                and not (projets.dossier(code) / "02-a-valider" / "cas-de-tests.json").exists():
            raise ErreurTache(analyse_sans_resultat(bilan))
        c = projets.controle(code)
        self.base.ajouter_journal(t["id"], f"Contrôle : {len(c['erreurs'])} erreur(s), {len(c['avertissements'])} avertissement(s). "
                                           f"Coût : {bilan.get('cout_usd', 0)} USD.")
        r = self.base.tache(t["id"])["resultat"] or {}
        r["controle"] = c
        self.base.maj_tache(t["id"], resultat=r)

    def _publier(self, t):
        code = t["projet"]
        d = projets.dossier(code)
        if not (d / "03-valide" / "cas-de-tests.json").exists():
            raise ErreurTache("Rien de validé à publier (03-valide est vide).")
        c = projets.controle(code, "03-valide")
        if not c["ok"]:
            raise ErreurTache("Le contrôle de 03-valide signale des erreurs : " + " ; ".join(c["erreurs"][:5]))
        # Fichier réellement envoyé : sans les cas suspendus à une question bloquante, avec les jeux de données.
        prep = projets.preparer_publication(code)
        fjson = prep["fichier"]
        from qa_commun import empreinte
        emp = empreinte(fjson) + ":" + empreinte(prep["jeux"])
        appliquer = t["type"] == "publier"
        if appliquer and t["parametres"].get("empreinte") != emp:
            raise ErreurTache("Les cas, les réponses aux questions ou les jeux de données ont changé depuis la vérification : "
                              "recommencez l'envoi.")
        if not reglages.squash_mcp_dir or not reglages.squash_url:
            raise ErreurTache("Squash n'est pas configuré sur le serveur (SQUASH_MCP_DIR, SQUASH_TM_BASE_URL).")
        corr = d / "04-livrables" / "squash" / "correspondance.json"
        corr.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["node", str(reglages.racine / "saas" / "publier_squash.mjs"), "--fichier", str(fjson),
               "--correspondance", str(corr), "--jeux", str(prep["jeux"])]
        if appliquer:
            cmd.append("--appliquer")
        if prep["exclus"]:
            self.base.ajouter_journal(t["id"], f"{len(prep['exclus'])} cas en attente d'une réponse bloquante, non envoyés : "
                                               + ", ".join(sorted(prep["exclus"])))
        self.base.ajouter_journal(t["id"], "Publication réelle en cours (environ 15 s par élément)..." if appliquer
                                  else "Simulation : lecture de Squash, rien n'est créé.")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=6 * 3600, env=dict(os.environ, SQUASH_MCP_DIR=reglages.squash_mcp_dir))
        try:
            res = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise ErreurTache(f"Réponse illisible du module Squash : {(r.stderr or r.stdout)[:400]}")
        res["exclus"] = prep["exclus"]
        plan = res.get("plan") or []
        resume = {a: sum(1 for x in plan if x.get("action") == a) for a in ("creer", "existe", "recreer")}
        res["resume"] = resume
        res["empreinte"] = emp
        self.base.maj_tache(t["id"], resultat=res)
        if res.get("erreurs"):
            raise ErreurTache(expliquer_erreur_squash(res["erreurs"]))
        if appliquer:
            n = len(res.get("crees") or [])
            j = res.get("jeux") or {}
            if j.get("crees") or j.get("completes"):
                self.base.ajouter_journal(t["id"], f"Jeux de données : {j.get('crees', 0)} créé(s), {j.get('completes', 0)} complété(s).")
            projets.journaliser(code, "publier", f"{n} élément(s) créé(s) dans Squash (projet {(res.get('projet') or {}).get('id')}), "
                                f"tâche {t['id']}", ["04-livrables/squash/correspondance.json"])
            self.base.ajouter_journal(t["id"], f"{n} élément(s) créé(s) dans Squash.")
        else:
            self.base.ajouter_journal(t["id"], f"Plan : {resume['creer']} à créer, {resume['existe']} déjà présent(s), "
                                               f"{resume['recreer']} à recréer.")

    def _specs(self, t):
        code = t["projet"]
        if not (projets.dossier(code) / "03-valide" / "cas-de-tests.json").exists():
            raise ErreurTache("Les specs se génèrent depuis la version validée (03-valide).")
        r = projets.script("generer_specs.py", code)
        for l in (r.stdout or "").splitlines():
            self.base.ajouter_journal(t["id"], l)
        if r.returncode:
            raise ErreurTache((r.stderr or r.stdout)[-400:])


def analyse_sans_resultat(bilan: dict) -> str:
    """Message quand l'assistant s'arrête sans avoir écrit de cas de tests."""
    dit = " ".join((bilan.get("compte_rendu") or "").split())
    if len(dit) > 500:
        dit = dit[:500].rsplit(" ", 1)[0] + "…"
    message = "L'assistant s'est arrêté sans produire de cas de tests."
    if dit:
        message += f" Son dernier message : « {dit} »"
    return message + (" Si les documents sont complets, relancez l'analyse ; avec un modèle gratuit ou léger, "
                      "ce cas est fréquent : un modèle plus puissant est recommandé.")


gestionnaire = Gestionnaire()


# ---------------------------------------------------------------- progression affichée

MESSAGES_ANALYSE = ((0, "Lecture du cahier des charges"), (25, "Repérage des exigences et des zones floues"),
                    (45, "Conception des cas de tests"), (70, "Mise en forme Excel et Word"),
                    (85, "Contrôle de cohérence"), (100, "Génération terminée"))


def progression(t) -> dict:
    """Pourcentage et message à afficher pour une tâche (estimation honnête : 100 % seulement à la fin réelle)."""
    import json as _json
    import math
    import time
    from datetime import datetime
    statut = t["statut"]
    if statut == "termine":
        return {"pourcentage": 100, "message": "Génération terminée" if t["type"] in ("analyser", "corriger")
                else ("Envoyé dans Squash" if t["type"] == "publier" else "Terminé")}
    if statut in ("echec", "annule", "interrompue"):
        dernier = (t["journal"] or [{}])[-1].get("m", "")
        return {"pourcentage": 0, "message": dernier.replace("Échec : ", "")}
    try:
        debut = datetime.fromisoformat(t["debut"]).timestamp() if t["debut"] else time.time()
    except ValueError:
        debut = time.time()
    ecoule = max(0.0, time.time() - debut)
    if t["type"] in ("analyser", "corriger"):
        p = 4 + 58 * (1 - math.exp(-ecoule / 300))
        etapes = ((t["resultat"] or {}).get("etapes") or [])
        p = max(p, min(62, 4 + 3 * sum(1 for e in etapes if e.get("statut") == "completed")))
        try:
            d = projets.dossier(t["projet"]) / "02-a-valider"
            if (d / "cas-de-tests.json").exists():
                p = max(p, 70)
            if (d / "cas-de-tests.xlsx").exists():
                p = max(p, 85)
        except projets.ErreurProjet:
            pass
        if any("Contrôle" in j.get("m", "") for j in t["journal"] or []):
            p = max(p, 95)
        p = min(p, 97)
        message = [m for seuil, m in MESSAGES_ANALYSE if p >= seuil][-1]
        minutes = int(ecoule // 60)
        if minutes:
            message += f" · {minutes} min"
        return {"pourcentage": round(p, 1), "message": message}
    if t["type"] == "publier":
        total = int((t["parametres"] or {}).get("a_creer") or 0)
        fait = 0
        try:
            c = _json.loads((projets.dossier(t["projet"]) / "04-livrables" / "squash" / "correspondance.json").read_text(encoding="utf-8"))
            fait = sum(len(c.get(k) or {}) for k in ("exigences", "cas_de_tests", "dossiers_exigences", "dossiers_cas"))
            fait -= int((t["parametres"] or {}).get("deja") or 0)
        except Exception:  # noqa: BLE001
            pass
        p = 3 + 94 * (max(0, fait) / total) if total else 3 + 60 * (1 - math.exp(-ecoule / 120))
        return {"pourcentage": round(min(p, 97), 1), "message": f"Création dans Squash : {max(0, fait)} sur {total}" if total else "Envoi dans Squash"}
    return {"pourcentage": round(min(97, 10 + 80 * (1 - math.exp(-ecoule / 10))), 1), "message": "Lecture de Squash"}
