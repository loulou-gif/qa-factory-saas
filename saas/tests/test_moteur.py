# -*- coding: utf-8 -*-
"""Reprise automatique d'une session après une coupure passagère de la connexion au modèle (ECONNRESET…)."""
import pytest

MUET = {"name": "APIError", "data": {"message": "Cannot connect to API: ECONNRESET"}}  # le modèle n'a rien répondu
COUPURE = {"name": "APIError", "data": {"message": "Cannot connect to API: ECONNRESET: The socket connection was closed unexpectedly."}}


class Reponse:
    def __init__(self, corps, statut=200):
        self.corps, self.status_code, self.text = corps, statut, ""

    def json(self):
        return self.corps

    def raise_for_status(self):
        pass


class FauxClient:
    def __init__(self, erreurs):
        self.erreurs, self.envois = list(erreurs), []

    def post(self, chemin, json=None, timeout=None):
        if chemin == "/session":
            return Reponse({"id": "ses_1"})
        if chemin.endswith("/abort"):
            return Reponse({})
        self.envois.append((chemin, json))
        erreur = self.erreurs.pop(0) if self.erreurs else None
        parts = [] if erreur is MUET else [{"type": "text", "text": "début du travail"}]
        return Reponse({"info": {"error": erreur} if erreur else {}, "parts": parts})

    def get(self, chemin, timeout=None):
        return Reponse([])


@pytest.fixture()
def moteur_factice(espace, monkeypatch):
    from app import moteur as module
    from app.config import reglages
    m = module.Moteur()
    monkeypatch.setattr(reglages, "modele", "opencode/modele-gratuit")
    monkeypatch.setattr(reglages, "intervalle_suivi_s", 0.01)
    return m, module


def nouvelle_tache(base):
    cur = base.x("INSERT INTO taches (projet, type, statut, parametres, cree_par, cree_le) VALUES ('p', 'automatiser', 'en_cours', '{}', 1, '2026-11-06')")
    return cur.lastrowid


def test_reprise_apres_coupure(moteur_factice):
    from app.main import base
    m, module = moteur_factice
    m._client = FauxClient([COUPURE, COUPURE, None])
    tid = nouvelle_tache(base)
    m.executer(base, tid, "automatiser", "saucedemo generation 1", outils={"nav*": False, "nav1_*": True})
    envois = m._client.envois
    assert len(envois) == 3
    assert envois[1][0] == "/session/ses_1/message" and "Reprends" in envois[1][1]["parts"][0]["text"]
    assert envois[1][1]["tools"] == {"nav*": False, "nav1_*": True}  # toujours le seul navigateur de la tâche
    journal = " ".join(j["m"] for j in base.tache(tid)["journal"])
    assert "reprise 1 sur 3" in journal and "reprise 2 sur 3" in journal


def test_abandon_apres_trop_de_coupures_ou_erreur_definitive(moteur_factice):
    from app.main import base
    m, module = moteur_factice
    m._client = FauxClient([COUPURE] * 5)
    with pytest.raises(module.ErreurMoteur, match="coupée à plusieurs reprises"):
        m.executer(base, nouvelle_tache(base), "analyser", "p")
    assert len(m._client.envois) == 1 + module.REPRISES_MAX
    m._client = FauxClient([{"name": "ProviderAuthError", "data": {"message": "invalid api key"}}])
    with pytest.raises(module.ErreurMoteur, match="refuse la clé"):
        m.executer(base, nouvelle_tache(base), "analyser", "p")
    assert len(m._client.envois) == 1


def test_pas_de_reprise_si_le_modele_ne_repond_jamais(moteur_factice):
    """Quota gratuit épuisé : OpenCode a déjà réessayé, aucune réponse du modèle : arrêt immédiat avec une explication."""
    from app.main import base
    m, module = moteur_factice
    m._client = FauxClient([MUET])
    with pytest.raises(module.ErreurMoteur, match="jamais répondu"):
        m.executer(base, nouvelle_tache(base), "analyser", "p")
    assert len(m._client.envois) == 1


LIMITE = {"name": "APIError", "data": {"message": "Rate limit exceeded: free-models-per-day", "statusCode": 429}}


def test_modele_de_secours_quand_la_limite_est_atteinte(moteur_factice):
    from app.main import base
    m, module = moteur_factice
    m._client = FauxClient([LIMITE, MUET, None])
    tid = nouvelle_tache(base)
    bilan = m.executer(base, tid, "analyser", "p", modele="google/gemini-2.5-flash",
                       secours=["google/gemini-2.5-flash", "openrouter/openrouter/free", "opencode/big-pickle"])
    envois = m._client.envois
    assert len(envois) == 3 and envois[0][1]["model"] == "google/gemini-2.5-flash"  # premier envoi : API des commandes
    assert envois[1][1]["model"] == {"providerID": "openrouter", "modelID": "openrouter/free"}
    assert envois[2][1]["model"] == {"providerID": "opencode", "modelID": "big-pickle"} and "limite" in envois[2][1]["parts"][0]["text"]
    journal = " ".join(j["m"] for j in base.tache(tid)["journal"])
    assert "Limite atteinte avec google/gemini-2.5-flash" in journal and "continue avec opencode/big-pickle" in journal
    assert bilan.get("modele") == "opencode/big-pickle" or base.tache(tid)["resultat"]["modele"] == "opencode/big-pickle"
    # Plus de secours : l'erreur est expliquée
    m._client = FauxClient([LIMITE])
    with pytest.raises(module.ErreurMoteur, match="modèles de secours"):
        m.executer(base, nouvelle_tache(base), "analyser", "p", modele="google/gemini-2.5-flash")
    # Une clé absente (relais) passe aussi au suivant
    m._client = FauxClient([{"name": "ProviderAuthError", "data": {"message": "Aucune clé d'API DeepSeek"}}, None])
    m.executer(base, nouvelle_tache(base), "analyser", "p", modele="deepseek/deepseek-flash", secours=["anthropic/claude-haiku-5-5"])
    assert m._client.envois[1][1]["model"]["providerID"] == "anthropic"
