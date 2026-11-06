# -*- coding: utf-8 -*-
"""Documents de recette et paramètres de l'outil : modèles Excel et Word de l'entreprise, rédaction du manuel
(contrôle du contenu écrit par l'agent), modèles d'IA et clés d'API, relais vers le fournisseur, menu latéral.

Ne lance pas le moteur IA : cd saas && python -m pytest -q tests/test_documents.py
"""
import io
import json
import shutil
import struct
import zlib

import httpx
import openpyxl
import pytest
from openpyxl.styles import Border, Font, PatternFill, Side

from conftest import connecter, csrf, jx
from test_parametres import MDP, creer
from test_tests_application import projet_valide

SECRETS = {"COMPTE_1_IDENTIFIANT": "standard_user", "COMPTE_1_MOT_DE_PASSE": "secret_sauce"}


def admin_doc():
    """Administrateur prêt à l'emploi (l'administrateur initial doit d'abord changer son mot de passe)."""
    from app.main import base
    uid = creer("admin-doc")
    base.x("UPDATE utilisateurs SET role = 'admin' WHERE id = ?", (uid,))
    return "admin-doc"


def png(chemin, w=320, h=200):
    brut = b"".join(b"\x00" + bytes([210, 225, 245]) * w for _ in range(h))

    def bloc(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    chemin.write_bytes(b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                       + bloc(b"IDAT", zlib.compress(brut)) + bloc(b"IEND", b""))


def classeur_entreprise() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Recette"
    ws["A1"] = "Cahier de recette – {{PROJET}}"
    ws["A2"] = "Version {{VERSION}} du {{DATE}} · {{INCONNU}}"
    bord = Border(*(Side(style="thin"),) * 4)
    for i, t in enumerate(["Réf.", "Module", "Scénario", "Pré-requis", "N° étape", "Action à réaliser",
                           "Résultat attendu (expected)", "Résultat obtenu", "Statut", "Commentaires"], 1):
        c = ws.cell(5, i, t)
        c.font, c.fill, c.border = Font(bold=True), PatternFill("solid", fgColor="1F4E78"), bord
        ws.cell(6, i, "exemple").border = bord
    ws.cell(7, 1, "exemple 2")
    f = io.BytesIO()
    wb.save(f)
    return f.getvalue()


def document_entreprise() -> bytes:
    import docx
    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "ACME – {{PROJET}}"
    d.add_heading("{{TITRE}}", 0)
    p = d.add_paragraph("Version {{VERSION}} du ")
    p.add_run("{{DA").bold = True
    p.add_run("TE}}")
    d.add_paragraph("{{SOMMAIRE}}")
    p = d.add_paragraph()
    p.add_run("{{CONT")
    p.add_run("ENU}}")
    d.add_paragraph("Fin du modèle ACME.")
    f = io.BytesIO()
    d.save(f)
    return f.getvalue()


def contenu_agent():
    return {"titre": "Manuel d'utilisation – SauceDemo", "sous_titre": "Boutique", "blocs": [
        {"type": "titre", "niveau": 1, "texte": "Préambule", "numerote": False},
        {"type": "paragraphe", "texte": "Ce manuel décrit **SauceDemo** & ses <écrans>."},
        {"type": "titre", "niveau": 1, "texte": "Se connecter"},
        {"type": "procedure", "texte": "Ouvrir une session"},
        {"type": "etapes", "elements": ["Ouvrez le lien.", "Saisissez standard_user.", "Cliquez sur **Login**."]},
        {"type": "capture", "fichier": "connexion.png", "legende": "Page de connexion"},
        {"type": "capture", "fichier": "../../projet.json", "legende": "chemin interdit"},
        {"type": "capture", "fichier": "absente.png", "legende": "absente"},
        {"type": "note", "libelle": "Remarque", "texte": "Mot de passe secret_sauce masqué."},
        {"type": "script", "texte": "inconnu"}],
        "couverture": [{"fonctionnalite": "Authentification", "cas": ["CT0001"], "etat": "verifie"}],
        "points_a_confirmer": ["Message d'erreur de connexion non observé."]}


def test_cahier_au_modele_de_l_entreprise(espace, tmp_path):
    import cahier_modele as cm
    a = cm.analyser(classeur_entreprise())
    assert a["ligne_entetes"] == 5 and a["mode"] == "etapes"
    champs = {c["lettre"]: c["champ"] for c in a["colonnes"]}
    assert champs == {"A": "id", "B": "fonctionnalite", "C": "titre", "D": "prerequis", "E": "numero_etape", "F": "action",
                      "G": "attendu", "H": "obtenu", "I": "statut", "J": "commentaire"}
    assert a["marqueurs"] == ["PROJET", "VERSION", "DATE"] and "{{INCONNU}}" in a["avertissements"][0]

    # Le modèle interne est lui aussi reconnu par l'analyse générique.
    interne = cm.analyser((espace["racine"] / "templates" / "cahier" / "modele_cahier.xlsx").read_bytes())
    assert interne["ligne_entetes"] == 31 and {"id", "action", "attendu"} <= {c["champ"] for c in interne["colonnes"]}

    for mauvais, motif in ((b"pas un zip", "pas un classeur"), (document_entreprise(), "pas un classeur")):
        with pytest.raises(cm.ErreurModele, match=motif):
            cm.analyser(mauvais)
    vide = openpyxl.Workbook()
    vide.active["A1"] = "Rien"
    f = io.BytesIO()
    vide.save(f)
    with pytest.raises(cm.ErreurModele, match="Tableau des cas introuvable"):
        cm.analyser(f.getvalue())

    code = "documents-cahier"
    projet_valide(espace["racine"], code)
    modele = tmp_path / "modele.xlsx"
    modele.write_bytes(classeur_entreprise())
    out, n = cm.generer(code, modele, nominaux=True)
    ws = openpyxl.load_workbook(out)["Recette"]
    assert ws["A1"].value == "Cahier de recette – SauceDemo" and "{{INCONNU}}" in ws["A2"].value and "{{" not in ws["A2"].value.replace("{{INCONNU}}", "")
    assert [ws.cell(6, c).value for c in (1, 2, 3, 5)] == ["CT0001", "Authentification", "Se connecter avec un compte valide", 1]
    assert ws.cell(7, 5).value == 2 and ws.cell(7, 1).value is None and ws.cell(6, 8).value is None and ws.cell(6, 9).value is None
    assert "A6:A8" in {str(r) for r in ws.merged_cells.ranges}
    assert ws.cell(6, 1).border.left.style == "thin"  # mise en forme de la ligne d'exemple reprise
    data = json.loads((espace["racine"] / "projets" / code / "03-valide" / "cas-de-tests.json").read_text(encoding="utf-8"))
    nominaux = [c for c in data["cas_de_tests"] if c["type"] == "nominal"]
    assert n == len(nominaux) and sum(1 for r in range(6, ws.max_row + 1) if ws.cell(r, 1).value) == n


def test_manuel_controle_et_mise_en_page(espace):
    import docx
    import manuel
    code = "documents-manuel"
    projet_valide(espace["racine"], code)
    g = manuel.preparer(code, "https://www.saucedemo.com/", ["Client"], navigateur="nav9", fonctions=["Authentification"])
    fiche = json.loads((g / "redaction.json").read_text(encoding="utf-8"))
    assert [f["nom"] for f in fiche["fonctionnalites"]] == ["Authentification"]
    assert fiche["comptes"] == [{"role": "Client", "identifiant": "COMPTE_1_IDENTIFIANT", "mot_de_passe": "COMPTE_1_MOT_DE_PASSE"}]
    assert "standard_user" not in json.dumps(fiche)

    with pytest.raises(manuel.ErreurManuel, match="contenu.json absent"):
        manuel.construire(code, g.name)
    png(g / "captures" / "connexion.png")
    (g / "contenu.json").write_text(json.dumps(contenu_agent(), ensure_ascii=False), encoding="utf-8")

    # Modèle interne : contenu contrôlé (secrets masqués, chemins et captures absentes retirés, bloc inconnu ignoré)
    s = manuel.construire(code, g.name, None, secrets=SECRETS.values())
    assert s["modele"] == "interne" and s["figures"] == 1 and s["chapitres"] == 2 and s["procedures"] == 1
    av = " ".join(s["avertissements"])
    assert "absente.png" in av and "projet.json" in av and "script" in av and "2 valeur(s) de compte" in av
    controle = (g / "contenu.controle.json").read_text(encoding="utf-8")
    assert "standard_user" not in controle and "secret_sauce" not in controle
    texte = "\n".join(p.text for p in docx.Document(espace["racine"] / "projets" / code / s["chemin"]).paragraphs)
    assert "Ouvrir une session" in texte and "<secret>" in texte and "secret_sauce" not in texte
    points = (espace["racine"] / "projets" / code / s["points"]).read_text(encoding="utf-8")
    assert "Message d'erreur de connexion non observé." in points and "Vérifié dans l'application" in points

    # Modèle de l'entreprise : styles du modèle, marqueurs remplacés (même coupés en morceaux), en-tête, sommaire
    import manuel_modele
    modele = g.parent.parent / "modele.docx"
    modele.write_bytes(document_entreprise())
    a = manuel_modele.analyser(modele)
    assert a["emplacement"] == "marqueur" and a["sommaire"] and a["titres"] == 3 and "DATE" in a["marqueurs"]
    s = manuel.construire(code, g.name, modele, secrets=SECRETS.values())
    d = docx.Document(espace["racine"] / "projets" / code / s["chemin"])
    paras = [(p.style.name, p.text) for p in d.paragraphs]
    assert ("Title", "Manuel d'utilisation – SauceDemo") in paras and ("Heading 1", "Se connecter") in paras
    assert any(t.startswith("Version V1.0 du ") and "{{" not in t for _, t in paras)
    assert ("Caption", "Figure 1 – Page de connexion") in paras and paras[-1] == ("Normal", "Fin du modèle ACME.")
    assert not any("{{" in t for _, t in paras) and d.sections[0].header.paragraphs[0].text == "ACME – SauceDemo"
    assert len(d.inline_shapes) == 1
    import zipfile
    with zipfile.ZipFile(espace["racine"] / "projets" / code / s["chemin"]) as z:
        assert 'w:updateFields w:val="true"' in z.read("word/settings.xml").decode()
        assert ' TOC \\o "1-3"' in z.read("word/document.xml").decode()
    assert [r["redaction"] for r in manuel.redactions(code)] == [g.name]


def test_modeles_ia_cles_et_relais(espace, monkeypatch):
    from app import parametres, relais_ia
    from app.main import base
    from app.config import reglages
    admin = {"id": base.un("SELECT id FROM utilisateurs WHERE identifiant = 'admin'")["id"], "nom": "Admin"}

    # Rien de réglé : modèle et clé du serveur
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-du-serveur")
    assert parametres.modele_pour(base, "analyser") == reglages.modele
    assert parametres.cle_pour(base, "openrouter") == "cle-du-serveur" and parametres.cle_pour(base, "anthropic") == ""

    avant = parametres.enregistrer_ia(base, "openrouter/anthropic/claude-haiku-5.5", {"documents": "anthropic/claude-sonnet-5-5"},
                                      {"openrouter": "sk-or-cle-app-1234"}, [], admin)
    assert parametres.modele_pour(base, "analyser") == "openrouter/anthropic/claude-haiku-5.5"
    assert parametres.modele_pour(base, "manuel") == "anthropic/claude-sonnet-5-5"
    assert parametres.cle_pour(base, "openrouter") == "sk-or-cle-app-1234"
    brut = base.un("SELECT valeur FROM reglages_app WHERE cle = 'cle_ia:openrouter'")["valeur"]
    assert "sk-or-cle-app" not in brut and parametres.resume_ia(base)["cles"]["openrouter"]["fin"] == "1234"
    with pytest.raises(parametres.ErreurParametres):
        parametres.enregistrer_ia(base, "pas un modèle", {}, {}, [], admin)
    with pytest.raises(parametres.ErreurParametres, match="non pris en charge"):
        parametres.enregistrer_ia(base, "inconnu/modele", {}, {}, [], admin)

    # Relais : jeton interne exigé, routes d'inférence seulement, clé de l'application ajoutée, réponse relayée
    vus = []

    def fournisseur(req):
        req.read()
        vus.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(b"data: {\"ok\":1}\n\n"))
    vrai = httpx.AsyncClient
    monkeypatch.setattr(relais_ia.httpx, "AsyncClient", lambda **kw: vrai(transport=httpx.MockTransport(fournisseur)))
    c = espace["client"]
    jeton = relais_ia.jeton_relais()
    assert jeton
    corps = {"model": "anthropic/claude-haiku-5.5", "messages": []}
    assert c.post("/ia/openrouter/chat/completions", json=corps, headers={"Authorization": "Bearer faux"}).status_code == 401
    assert c.post("/ia/openrouter/credits", json=corps, headers={"Authorization": f"Bearer {jeton}"}).status_code == 404
    assert c.post("/ia/inconnu/chat/completions", json=corps, headers={"Authorization": f"Bearer {jeton}"}).status_code == 404
    r = c.post("/ia/openrouter/chat/completions", json=corps, headers={"Authorization": f"Bearer {jeton}", "X-Title": "opencode"})
    assert r.status_code == 200 and r.text == "data: {\"ok\":1}\n\n"
    assert str(vus[-1].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert vus[-1].headers["authorization"] == "Bearer sk-or-cle-app-1234" and vus[-1].headers["x-title"] == "opencode"
    assert json.loads(vus[-1].content) == corps
    # Anthropic : jeton reçu dans x-api-key, aucune clé nulle part -> message clair
    r = c.post("/ia/anthropic/messages", json=corps, headers={"x-api-key": jeton})
    assert r.status_code == 401 and "Paramètres > Modèles d'IA" in r.json()["error"]["message"]

    parametres.restaurer(base, avant)
    assert parametres.modele_pour(base, "analyser") == reglages.modele and parametres.cle_pour(base, "openrouter") == "cle-du-serveur"


def test_pages_parametres_documents_et_menu(espace, monkeypatch):
    from app import parametres
    from app.main import base, moteur
    c = espace["client"]
    connecter(c, admin_doc(), MDP)
    code = "documents-pages"
    projet_valide(espace["racine"], code)

    # Menu latéral : entrées principales sans sous-menu, Paramètres en bas, au-dessus de l'utilisateur
    h = c.get(f"/projets/{code}").text
    assert 'class="menu-lateral"' in h and "Nouvelle analyse" in h and "Activité" in h and "sous-menu" not in h
    assert f'href="/projets/{code}/documents"' in h and "Documents de recette" in h
    assert h.index("Activité") < h.index(">Paramètres<") < h.index("Déconnexion")
    h = c.get("/parametres").text
    for x in ("Connexion Squash", "Modèles d'IA", "Modèles de documents", "Équipe", "Mon compte"):
        assert x in h
    assert c.get("/activite").status_code == 200

    # Modèle de cahier de l'entreprise : dépôt analysé, cahier produit dans ce modèle
    r = c.post("/parametres/documents/cahier", data={"csrf": csrf(c, "/parametres/documents")},
               files={"fichier": ("Modèle ACME.xlsx", classeur_entreprise(), "application/octet-stream")})
    assert r.status_code == 200 and "Modèle ACME.xlsx" in r.text and "Action à réaliser" in r.text
    r = c.post("/parametres/documents/manuel", data={"csrf": csrf(c, "/parametres/documents")},
               files={"fichier": ("faux.docx", b"pas un document", "application/octet-stream")})
    assert "Modèle refusé" in r.text and parametres.chemin_modele("manuel") is None
    for ancien in (espace["racine"] / "projets" / code / "04-livrables" / "cahier").glob("*.xlsx"):
        ancien.unlink()  # cahiers déjà produits dans le projet de démonstration copié
    r = c.post(f"/projets/{code}/cahier", data={"csrf": csrf(c, f"/projets/{code}/documents")})
    assert r.status_code == 200 and "au modèle de l&#39;entreprise" in r.text
    fichiers = list((espace["racine"] / "projets" / code / "04-livrables" / "cahier").glob("*.xlsx"))
    assert len(fichiers) == 1 and openpyxl.load_workbook(fichiers[0])["Recette"]["A6"].value == "CT0001"
    c.post("/parametres/documents/cahier/retirer", data={"csrf": csrf(c, "/parametres/documents")})
    assert parametres.chemin_modele("cahier") is None

    # Manuel : il faut le lien de l'application
    r = jx(c, f"/projets/{code}/manuel", {"fonctionnalites": ["Authentification"]}, page=f"/projets/{code}/documents")
    assert r.status_code == 409

    # Modèles d'IA : réservé à l'administrateur, essai avant enregistrement, retour en arrière si l'essai échoue
    monkeypatch.setattr(moteur, "disponible", lambda: (True, ""))
    monkeypatch.setattr(moteur, "modeles_disponibles", lambda: {"openrouter": ["anthropic/claude-haiku-5.5"]})
    essais = []
    monkeypatch.setattr(moteur, "essayer_modele", lambda m, uid=None: (essais.append(m) or (m != "openrouter/mauvais/modele", "modèle inconnu")))
    h = c.get("/parametres/modeles").text
    assert 'value="openrouter/anthropic/claude-haiku-5.5"' in h  # suggestion du moteur
    r = c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "openrouter/mauvais/modele",
                                            "cle_openrouter": "sk-or-essai-9999"})
    assert "l&#39;essai a échoué" in r.text and parametres.config_ia(base)["principal"] == ""
    assert not parametres.resume_ia(base)["cles"]["openrouter"]["enregistree"]
    r = c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "openrouter/anthropic/claude-haiku-5.5",
                                            "cle_openrouter": "sk-or-essai-9999"})
    assert "Modèles d&#39;IA enregistrés" in r.text and "…9999" in r.text and "sk-or-essai-9999" not in r.text
    assert parametres.modele_pour(base, "tester") == "openrouter/anthropic/claude-haiku-5.5"
    r = c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "", "retirer_openrouter": "1"})
    assert parametres.config_ia(base)["principal"] == "" and not parametres.resume_ia(base)["cles"]["openrouter"]["enregistree"]

    creer("lecteur-doc")
    connecter(c, "lecteur-doc", MDP)
    assert "Réglé par l'administrateur" in c.get("/parametres/modeles").text
    assert c.post("/parametres/modeles", data={"csrf": csrf(c, "/parametres/modeles"), "principal": "x/y"}).status_code == 403
    r = c.post("/parametres/documents/cahier", data={"csrf": csrf(c, "/parametres/documents")},
               files={"fichier": ("m.xlsx", classeur_entreprise(), "application/octet-stream")})
    assert r.status_code == 403
    connecter(c, "admin-doc", MDP)
    shutil.rmtree(espace["racine"] / "projets" / code, ignore_errors=True)
