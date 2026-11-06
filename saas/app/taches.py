# -*- coding: utf-8 -*-
"""File des tâches longues : analyse et corrections (IA), publication Squash, specs.

Une seule tâche active par projet (pas d'écritures concurrentes dans un même dossier) ;
un nombre limité de tâches en parallèle sur le serveur (QAF_TACHES_PARALLELES).
"""
import json
from concurrent.futures import ThreadPoolExecutor

from . import campagnes, connexions, projets
from .config import reglages
from .db import STATUTS_ACTIFS, maintenant
from .moteur import ErreurMoteur, moteur

TYPES = {
    "analyser": "Analyse du cahier des charges",
    "corriger": "Correction demandée",
    "publier-simulation": "Simulation de publication Squash",
    "publier": "Publication dans Squash",
    "specs": "Specs d'automatisation",
    "tester": "Tests de l'application",
}
STATUTS = {
    "en_attente": "En attente", "en_cours": "En cours", "attente_confirmation": "Confirmation demandée",
    "termine": "Terminée", "echec": "Échec", "annule": "Annulée", "interrompue": "Interrompue",
}


class ErreurTache(Exception):
    pass


LIBELLES_CHAMPS = {"titre": "titre", "description": "description", "prerequis": "prérequis", "importance": "importance",
                   "statut": "statut", "nature": "nature", "type": "type", "etapes": "étapes", "exigences": "exigences couvertes",
                   "criticite": "criticité", "categorie": "catégorie"}


def details_plan(plan, fichier) -> list:
    """Éléments du plan qui demandent l'attention de la personne : mises à jour, changements faits dans Squash
    (conservés ou en conflit), références déjà présentes dans le projet. Titres repris du fichier envoyé."""
    try:
        f = json.loads(open(fichier, encoding="utf-8").read())
        titres = {x["id"]: x.get("titre", "") for x in (f.get("exigences") or []) + (f.get("cas_de_tests") or [])}
    except Exception:  # noqa: BLE001
        titres = {}
    lib = lambda champs: [LIBELLES_CHAMPS.get(c, c) for c in champs or []]  # noqa: E731
    sortie = []
    for l in plan:
        if l.get("type") not in ("exigence", "cas-de-test"):
            continue
        if l.get("action") not in ("modifier", "conflit", "homonyme") and not l.get("conserves"):
            continue
        sortie.append({"id": l["id"], "type": l["type"], "titre": titres.get(l["id"], ""), "action": l["action"],
                       "version": l.get("version") or "",
                       "squash_id": l.get("squash_id"), "champs": lib(l.get("champs")), "conserves": lib(l.get("conserves")),
                       "conflits": [{"libelle": c.get("libelle"), "squash": (c.get("squash") or "")[:1500],
                                     "fichier": (c.get("fichier") or "")[:1500]} for c in l.get("conflits") or []],
                       "detail": l.get("detail") or ""})
    return sortie


def dossier_racine(code: str) -> str:
    """Dossier créé dans Squash au premier envoi pour ranger tout ce que QA Factory y publie : le projet Squash
    peut déjà contenir des éléments de mêmes références (autre outil, ancienne publication), jamais touchés."""
    nom = (projets.fiche(code).get("nom") or code).strip()
    return f"QA Factory - {nom}"[:200]


def premier_envoi(corr) -> bool:
    """Vrai si rien n'a encore été publié avec cette correspondance (ou si elle a déjà un dossier racine)."""
    try:
        c = json.loads(open(corr, encoding="utf-8").read())
    except (OSError, ValueError):
        return True
    deja = any(c.get(k) for k in ("exigences", "cas_de_tests", "dossiers_exigences", "dossiers_cas"))
    return not deja or bool(c.get("dossier_racine"))


expliquer_erreur_squash = connexions.expliquer


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
                        "publier": self._publier, "specs": self._specs, "tester": self._tester}[t["type"]]
            fonction(t)
            t = self.base.tache(tid)
            self.base.maj_tache(tid, statut="annule" if t["annulation"] else "termine", fin=maintenant(), attente=None)
            self.base.ajouter_journal(tid, ((t["resultat"] or {}).get("message_arret") or "Arrêtée.") if t["annulation"] else "Terminée.")
        except (ErreurMoteur, ErreurTache, projets.ErreurProjet, connexions.ErreurConnexion, campagnes.ErreurCampagne) as e:
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
        # La connexion Squash est celle de la personne qui a lancé la tâche ; elle doit viser
        # la même instance que la vérification préalable.
        cx = connexions.lire(self.base, t["cree_par"])
        if not cx:
            raise ErreurTache("Aucune connexion à Squash : réglez-la dans la page Squash, puis recommencez.")
        instance = t["parametres"].get("instance")
        if instance and instance != cx["url"]:
            raise ErreurTache("La connexion Squash a changé depuis la vérification : recommencez l'envoi.")
        adresse = connexions.adresse_affichee(cx["url"])
        corr = d / "04-livrables" / "squash" / "correspondance.json"
        corr.parent.mkdir(parents=True, exist_ok=True)
        # Les éléments créés par QA Factory sont aussi mis à jour ; un changement fait dans Squash est conservé,
        # sauf conflit que la personne a choisi de remplacer (liste « forcer », vérifiée à la demande d'envoi).
        forcer = [str(x) for x in (t["parametres"].get("forcer") or [])]
        arguments = (["--fichier", fjson, "--correspondance", corr, "--jeux", prep["jeux"], "--mettre-a-jour"]
                     + (["--forcer", ",".join(forcer)] if forcer and appliquer else [])
                     + (["--dossier-racine", dossier_racine(code)] if premier_envoi(corr) else [])
                     + (["--appliquer"] if appliquer else []))
        if prep["exclus"]:
            self.base.ajouter_journal(t["id"], f"{len(prep['exclus'])} cas en attente d'une réponse bloquante, non envoyés : "
                                               + ", ".join(sorted(prep["exclus"])))
        self.base.ajouter_journal(t["id"], (f"Publication réelle vers {adresse} en cours (environ 15 s par élément)..." if appliquer
                                            else f"Simulation : lecture de {adresse}, rien n'est créé."))
        res = connexions.appeler_module(cx, *arguments, timeout=6 * 3600,
                                        arret=lambda: bool(self.base.tache(t["id"])["annulation"]),
                                        delai_arret=120 if appliquer else 0)
        res["exclus"] = prep["exclus"]
        res["instance"] = cx["url"]
        plan = res.get("plan") or []
        resume = {a: sum(1 for x in plan if x.get("action") == a) for a in ("creer", "existe", "recreer", "modifier", "conflit", "homonyme")}
        resume["conserves"] = sum(1 for x in plan if x.get("conserves"))
        res["resume"] = resume
        res["details"] = details_plan(plan, fjson)
        res["empreinte"] = emp
        self.base.maj_tache(t["id"], resultat=res)
        if res.get("erreurs"):
            raise ErreurTache(connexions.expliquer(res["erreurs"], adresse, cx["mode"]))
        if res.get("arrete"):
            n = len(res.get("crees") or [])
            if appliquer and n:
                projets.journaliser(code, "publier", f"{n} élément(s) créé(s) dans Squash avant l'arrêt, tâche {t['id']}",
                                    ["04-livrables/squash/correspondance.json"])
            self.base.maj_tache(t["id"], resultat={**res, "message_arret": (
                "Envoi arrêté de force : vérifiez dans Squash les derniers éléments créés avant de relancer." if res.get("force") else
                f"Envoi arrêté : {n} élément(s) créé(s) avant l'arrêt. Relancer l'envoi reprend la suite, sans doublon."
                if appliquer else "Vérification arrêtée.")})
            return
        if appliquer:
            n = len(res.get("crees") or [])
            m = len(res.get("modifies") or [])
            echecs = res.get("non_mis_a_jour") or []
            j = res.get("jeux") or {}
            if j.get("crees") or j.get("completes"):
                self.base.ajouter_journal(t["id"], f"Jeux de données : {j.get('crees', 0)} créé(s), {j.get('completes', 0)} complété(s).")
            for e in echecs:
                self.base.ajouter_journal(t["id"], e)
            projets.enregistrer_envoi(code, non_envoyes={e.split()[1] for e in echecs if len(e.split()) > 1})
            versions = [f"{x.get('version')} (remplace l'id {x.get('ancien_squash_id')}, passé en Obsolète)"
                        for x in res.get("modifies") or [] if x.get("version")]
            for v in versions:
                self.base.ajouter_journal(t["id"], "Nouvelle version " + v)
            projets.journaliser(code, "publier", f"{n} élément(s) créé(s), {m} mis à jour dans Squash (projet "
                                f"{(res.get('projet') or {}).get('id')})"
                                + (f", {len(forcer)} conflit(s) remplacé(s) : {', '.join(forcer)}" if forcer else "")
                                + (f", {len(echecs)} non mis à jour" if echecs else "")
                                + (f" ; nouvelles versions : {', '.join(x.split(' (')[0] for x in versions)}" if versions else "")
                                + f", tâche {t['id']}",
                                ["04-livrables/squash/correspondance.json"])
            self.base.ajouter_journal(t["id"], f"{n} élément(s) créé(s), {m} mis à jour dans Squash.")
        else:
            self.base.ajouter_journal(t["id"], f"Plan : {resume['creer']} à créer, {resume['modifier']} à mettre à jour, "
                                               f"{resume['conflit']} modifié(s) aussi dans Squash, {resume['homonyme']} déjà présent(s) "
                                               f"sans avoir été créé(s) par QA Factory, {resume['existe']} à jour, {resume['recreer']} à recréer.")

    def _tester(self, t):
        """Exécution des cas validés sur l'application par l'agent, dans un navigateur propre à la tâche."""
        import execution as outil
        code, tid = t["projet"], t["id"]
        d = projets.dossier(code)
        if not (d / "03-valide" / "cas-de-tests.json").exists():
            raise ErreurTache("Les cas doivent être validés avant d'être exécutés.")
        if (d / "02-a-valider" / "cas-de-tests.json").exists():
            raise ErreurTache("Des cas sont en relecture : terminez la relecture avant de lancer les tests.")
        app = campagnes.application(code)
        if not app["url"]:
            raise ErreurTache("Indiquez d'abord le lien de l'application (page Application testée).")
        for adresse in [app["url"], *app["autres_domaines"]]:
            campagnes.verifier_reseau(adresse)
        libelles, valeurs = campagnes.secrets(self.base, code)
        nom = campagnes.nom_navigateur(tid)
        try:
            c = outil.preparer(code, app["url"], libelles, app["actions"], modele=reglages.modele,
                               par=t.get("auteur") or "", navigateur=nom)
        except outil.ErreurExecution as e:
            raise ErreurTache(str(e))
        self.base.maj_tache(tid, parametres={**(t["parametres"] or {}), "campagne": c.name})
        self.base.ajouter_journal(tid, f"Campagne {c.name} : {len(json.loads((c / 'campagne.json').read_text(encoding='utf-8'))['cas'])} cas "
                                       f"sur {app['url']}, {len(libelles)} compte(s) de test, {campagnes.ACTIONS[app['actions']].lower()}.")
        simulation = reglages.modele.startswith("simulation/")
        try:
            if not simulation:  # le faux modèle de démonstration n'utilise pas de navigateur
                moteur.ajouter_navigateur(nom, campagnes.configuration_navigateur(tid, app, valeurs, c))
                self.base.ajouter_journal(tid, "Navigateur de test démarré (limité aux domaines de l'application).")
            bilan = moteur.executer(self.base, tid, "tester", f"{code} campagne {c.name}", outils=campagnes.outils_autorises(tid))
        finally:
            if not simulation:
                moteur.retirer_navigateur(nom)
        if not any((c / "resultats").glob("*.json")) and not self.base.tache(tid)["annulation"]:
            dit = " ".join((bilan.get("compte_rendu") or "").split())[:400]
            raise ErreurTache("L'assistant s'est arrêté sans enregistrer de résultat." + (f" Son dernier message : « {dit} »" if dit else "")
                              + " Vérifiez le lien et les comptes de test, puis relancez ; un modèle plus puissant est recommandé.")
        try:
            synthese = outil.consolider(code, c.name)
        except outil.ErreurExecution as e:
            raise ErreurTache(str(e))
        s = synthese["statistiques"]["cas"]
        r = self.base.tache(tid)["resultat"] or {}
        r.update(campagne=c.name, statistiques=s, modifications=synthese["modifications"])
        self.base.maj_tache(tid, resultat=r)
        self.base.ajouter_journal(tid, f"Résultats : {s['reussi']} réussi(s), {s['echoue']} échoué(s), {s['bloque']} bloqué(s), "
                                       f"{s['non_execute']} non exécuté(s) ; {synthese['modifications']} correction(s) de cas proposée(s). "
                                       f"Coût : {bilan.get('cout_usd', 0)} USD.")

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
                else ("Envoyé dans Squash" if t["type"] == "publier" else ("Tests terminés" if t["type"] == "tester" else "Terminé"))}
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
    if t["type"] == "tester":
        fait, total = 0, 0
        try:
            c = projets.dossier(t["projet"]) / "04-livrables" / "execution" / str((t["parametres"] or {}).get("campagne") or "_")
            total = len(_json.loads((c / "campagne.json").read_text(encoding="utf-8"))["cas"])
            fait = len(list((c / "resultats").glob("*.json")))
        except Exception:  # noqa: BLE001
            pass
        if not total:
            return {"pourcentage": 3, "message": "Préparation du navigateur de test"}
        minutes = int(ecoule // 60)
        return {"pourcentage": round(min(97, 3 + 94 * fait / total), 1),
                "message": f"Cas exécutés : {fait} sur {total}" + (f" · {minutes} min" if minutes else "")}
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
        if total and fait >= total and (t["parametres"] or {}).get("a_maj"):
            return {"pourcentage": 97, "message": "Mise à jour des éléments modifiés"}
        return {"pourcentage": round(min(p, 97), 1), "message": f"Création dans Squash : {max(0, fait)} sur {total}" if total
                else ("Mise à jour dans Squash" if (t["parametres"] or {}).get("a_maj") else "Envoi dans Squash")}
    return {"pourcentage": round(min(97, 10 + 80 * (1 - math.exp(-ecoule / 10))), 1), "message": "Lecture de Squash"}
