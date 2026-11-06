# -*- coding: utf-8 -*-
"""Modèles d'IA : liste déroulante, chaîne de secours, modèles gratuits partagés, clés personnelles, relais.

Ne lance pas le moteur IA : cd saas && python -m pytest -q tests/test_modeles_ia.py
"""
import json

import httpx
import pytest

from conftest import connecter, csrf
from test_parametres import MDP, creer


def admin_ia():
    from app.main import base
    uid = creer("admin-ia")
    base.x("UPDATE utilisateurs SET role = 'admin' WHERE id = ?", (uid,))
    return {"id": uid, "nom": "Admin-ia"}


@pytest.fixture()
def propre(espace, monkeypatch):
    """Paramètres d'IA vides avant et après le test ; aucune clé du serveur."""
    from app.main import base
    for v in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    base.x("DELETE FROM reglages_app WHERE cle = 'ia' OR cle LIKE 'cle_ia%'")
    yield espace
    base.x("DELETE FROM reglages_app WHERE cle = 'ia' OR cle LIKE 'cle_ia%'")


def test_secours_gratuits_et_cles_personnelles(propre):
    from app import parametres as P
    from app.main import base
    adm = admin_ia()
    testeur = creer("testeur-ia")

    # Modèles gratuits partagés : refusés tant que l'administrateur ne les a pas autorisés
    with pytest.raises(P.ErreurParametres, match="cocher d'abord"):
        P.enregistrer_ia(base, "google/gemini-2.5-flash", {}, {}, [], adm, secours=["opencode/big-pickle"])
    P.enregistrer_ia(base, "google/gemini-2.5-flash", {}, {}, [], adm, gratuits=True,
                     secours=["deepseek/deepseek-flash", "", "opencode/big-pickle", "deepseek/deepseek-flash", "openrouter/openrouter/free"])
    assert P.config_ia(base)["secours"] == ["deepseek/deepseek-flash", "opencode/big-pickle", "openrouter/openrouter/free"]

    # Sans clé : seuls les modèles sans clé (OpenCode) restent dans la chaîne
    assert P.secours_pour(base, "analyser", testeur) == ["opencode/big-pickle"]
    # Clé personnelle DeepSeek du testeur : elle sert pour ses tâches, pas pour celles des autres
    P.enregistrer_cles_personnelles(base, {"id": testeur}, {"deepseek": "sk-perso-deepseek-7777"}, [])
    assert P.secours_pour(base, "analyser", testeur) == ["deepseek/deepseek-flash", "opencode/big-pickle"]
    assert P.secours_pour(base, "analyser", adm["id"]) == ["opencode/big-pickle"]
    assert P.cle_pour(base, "deepseek", testeur) == "sk-perso-deepseek-7777" and P.cle_pour(base, "deepseek", adm["id"]) == ""
    brut = base.un("SELECT valeur FROM reglages_app WHERE cle = ?", (f"cle_ia_u:{testeur}:deepseek",))["valeur"]
    assert "sk-perso" not in brut and P.resume_cles_personnelles(base, testeur)["deepseek"]["fin"] == "7777"
    # Clé de l'entreprise : utilisée par tous, la clé personnelle reste prioritaire
    P.enregistrer_ia(base, "google/gemini-2.5-flash", {}, {"deepseek": "sk-entreprise-1111"}, [], adm, gratuits=True,
                     secours=["deepseek/deepseek-flash"])
    assert P.cle_pour(base, "deepseek", adm["id"]) == "sk-entreprise-1111" and P.cle_pour(base, "deepseek", testeur) == "sk-perso-deepseek-7777"
    # Le modèle principal (Google) n'a pas de clé : signalé comme inutilisable
    assert "google/gemini-2.5-flash" in P.resume_ia(base, testeur)["inutilisables"]
    P.enregistrer_cles_personnelles(base, {"id": testeur}, {}, ["deepseek"])
    assert P.cle_pour(base, "deepseek", testeur) == "sk-entreprise-1111"


def test_relais_cle_de_l_utilisateur_de_la_tache(propre, monkeypatch):
    from app import parametres as P, relais_ia
    from app.main import base, moteur
    adm = admin_ia()
    testeur = creer("testeur-relais")
    P.enregistrer_ia(base, "", {}, {"google": "cle-google-entreprise"}, [], adm)
    P.enregistrer_cles_personnelles(base, {"id": testeur}, {"google": "cle-google-perso"}, [])
    base.x("INSERT INTO taches (projet, type, statut, parametres, session_id, cree_par, cree_le) "
           "VALUES ('p', 'analyser', 'en_cours', '{}', 'ses_tache', ?, '2026-11-07')", (testeur,))
    # Sous-agent : session fille d'une session de tâche, retrouvée par le moteur
    monkeypatch.setattr(moteur, "_client", type("C", (), {"get": lambda self, chemin, timeout=None: type(
        "R", (), {"json": lambda s: {"parentID": "ses_tache"} if chemin == "/session/ses_fille" else {}})()})())
    moteur._sessions.clear()

    vus = []

    def fournisseur(req):
        req.read()
        vus.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(b"data: {}\n\n"))
    vrai = httpx.AsyncClient
    monkeypatch.setattr(relais_ia.httpx, "AsyncClient", lambda **kw: vrai(transport=httpx.MockTransport(fournisseur)))
    c, jeton = propre["client"], relais_ia.jeton_relais()
    chemin = "/ia/google/models/gemini-2.5-flash:streamGenerateContent?alt=sse"
    for session, attendu in (("ses_tache", "cle-google-perso"), ("ses_fille", "cle-google-perso"), ("ses_inconnue", "cle-google-entreprise"), ("", "cle-google-entreprise")):
        r = c.post(chemin, json={"contents": []}, headers={"x-goog-api-key": jeton, "x-opencode-session-id": session})
        assert r.status_code == 200, (session, r.text)
        assert vus[-1].headers["x-goog-api-key"] == attendu, session
        assert str(vus[-1].url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse"
        assert "x-opencode-session-id" not in vus[-1].headers and "authorization" not in vus[-1].headers
    # Essai d'un modèle : la session d'essai porte l'utilisateur qui essaie sa clé
    moteur.sessions_essai["ses_essai"] = testeur
    c.post(chemin, json={}, headers={"x-goog-api-key": jeton, "x-opencode-session-id": "ses_essai"})
    assert vus[-1].headers["x-goog-api-key"] == "cle-google-perso"
    moteur._client = None


def test_page_liste_deroulante_et_mes_cles(propre, monkeypatch):
    from app import parametres as P
    from app.main import base, moteur
    c = propre["client"]
    admin_ia()
    connecter(c, "admin-ia", MDP)
    monkeypatch.setattr(moteur, "disponible", lambda: (True, ""))
    monkeypatch.setattr(moteur, "modeles_disponibles", lambda: {})
    essais = []

    def essai(m, uid=None):
        essais.append((m, uid))
        if m.startswith("google/"):
            return False, "Le fournisseur d'IA refuse la clé : vérifier la clé d'API. Détail : API key not valid"
        if m.startswith("deepseek/"):
            return False, "Aucune clé d'API DeepSeek : la renseigner dans Paramètres > Modèles d'IA. Détail : …"
        return True, ""
    monkeypatch.setattr(moteur, "essayer_modele", essai)

    h = c.get("/parametres/modeles").text
    assert '<optgroup label="Gratuits avec une clé gratuite">' in h and 'value="google/gemini-3-flash-preview"' in h
    assert 'name="secours_5"' in h and 'name="principal_autre"' in h and "+ Ajouter un modèle de secours" in h
    assert "J'accepte que ce service gratuit" in h and "https://aistudio.google.com/apikey" in h
    # Rien à saisir tant que le modèle choisi n'a pas besoin de clé : blocs de clé et autorisation masqués
    assert '<div id="bloc-cles" hidden>' in h and 'id="bloc-gratuits" hidden' in h

    # Choix dans la liste, modèle saisi à la main (« autre »), secours ; une clé absente n'empêche pas d'enregistrer
    r = c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "opencode/big-pickle",
                                            "usage_analyse": P.AUTRE, "usage_analyse_autre": "deepseek/deepseek-reasoner-x",
                                            "secours_1": "deepseek/deepseek-flash", "secours_2": "opencode/glm-5.3-flash-free",
                                            "gratuits": "1"})
    assert "Modèles d&#39;IA enregistrés. À noter" in r.text and "Aucune clé d&#39;API DeepSeek" in r.text
    ia = P.config_ia(base)
    assert ia["principal"] == "opencode/big-pickle" and ia["usages"]["analyse"] == "deepseek/deepseek-reasoner-x"
    assert ia["secours"] == ["deepseek/deepseek-flash", "opencode/glm-5.3-flash-free"] and ia["gratuits"]
    h = c.get("/parametres/modeles").text
    assert 'value="deepseek/deepseek-reasoner-x"' in h  # « autre modèle » réaffiché dans son champ
    assert 'data-f="deepseek" >' in h or 'data-f="deepseek">' in h  # clé DeepSeek demandée : modèle DeepSeek choisi
    assert 'data-f="google" hidden' in h and 'id="bloc-gratuits" hidden' not in h
    # Gratuits partagés décochés : refusé, rien ne change
    r = c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "opencode/big-pickle"})
    assert "cocher d&#39;abord" in r.text and P.config_ia(base)["gratuits"]

    # Clés personnelles d'un testeur (non administrateur) : essayées avec sa clé, refusées si la clé est mauvaise
    creer("testeur-cles")
    connecter(c, "testeur-cles", MDP)
    uid = base.un("SELECT id FROM utilisateurs WHERE identifiant = 'testeur-cles'")["id"]
    h = c.get("/parametres/modeles").text
    assert "Réglé par l'administrateur" in h and 'name="ma_cle_deepseek"' in h and 'name="ma_cle_google"' not in h
    r = c.post("/parametres/modeles/mes-cles", data={"csrf": csrf(c, "/parametres/modeles"), "ma_cle_google": "AIza-mauvaise"})
    assert "Clés non enregistrées" in r.text and not P.resume_cles_personnelles(base, uid)["google"]["enregistree"]
    assert ("google/gemini-2.5-flash", uid) in essais or any(m.startswith("google/") and u == uid for m, u in essais)
    r = c.post("/parametres/modeles/mes-cles", data={"csrf": csrf(c, "/parametres/modeles"), "ma_cle_deepseek": "sk-deepseek-perso-4242"})
    assert "Vos clés sont enregistrées" in r.text and "Votre clé …4242" in r.text and "sk-deepseek-perso" not in r.text
    r = c.post("/parametres/modeles/mes-cles", data={"csrf": csrf(c, "/parametres/modeles"), "ma_cle_groq": "gsk_bonne_cle_4242"})
    assert "Vos clés sont enregistrées" in r.text and "gsk_bonne" not in r.text
    assert 'name="ma_cle_groq"' not in r.text  # Groq n'est pas utilisé : pas de champ affiché
    assert P.cle_pour(base, "groq", uid) == "gsk_bonne_cle_4242"
    r = c.post("/parametres/modeles/mes-cles", data={"csrf": csrf(c, "/parametres/modeles"), "retirer_ma_groq": "1"})
    assert not P.resume_cles_personnelles(base, uid)["groq"]["enregistree"]
    assert c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "x/y"}).status_code == 403
