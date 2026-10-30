# -*- coding: utf-8 -*-
"""Vues modifiables des cas de tests : Excel (cas-de-tests.xlsx) et Word (cas-de-tests.docx).

Le JSON reste la source. Ces deux fichiers en sont générés et peuvent être modifiés par un
testeur ; outils/synchroniser_vues.py reporte ensuite les modifications dans le JSON et
régénère les autres vues.

La comparaison se fait sur une « projection » : les champs qu'un testeur peut modifier
(exigences, cas, étapes, stratégie). Les autres champs du JSON (meta, automatisation…) sont
conservés tels quels à l'import.
"""
import re
import unicodedata

from qa_commun import TECHNIQUES, TYPES_CHANGEMENT, TYPES_TEST

# ---------------------------------------------------------------- libellés <-> codes

NATURES = {"nominal": "Nominal", "negatif": "Négatif", "limite": "Limite"}
TYPES_TEST_LIB = {k: v[0] for k, v in TYPES_TEST.items()}
TYPES_STRAT_LIB = {**TYPES_TEST_LIB, **TYPES_CHANGEMENT}
TECHNIQUES_LIB = {k: f"{v[0]} ({v[1]})" for k, v in TECHNIQUES.items()}
IMPORTANCES_LIB = {"VERY_HIGH": "Très haute", "HIGH": "Haute", "MEDIUM": "Moyenne", "LOW": "Faible"}
CRITICITES_LIB = {"CRITICAL": "Critique", "MAJOR": "Majeure", "MINOR": "Mineure", "UNDEFINED": "Non définie"}
CATEGORIES_LIB = {
    "CAT_FUNCTIONAL": "Fonctionnelle", "CAT_NON_FUNCTIONAL": "Non fonctionnelle", "CAT_PERFORMANCE": "Performance",
    "CAT_SECURITY": "Sécurité", "CAT_ERGONOMIC": "Ergonomie", "CAT_USER_STORY": "User story",
    "CAT_BUSINESS": "Métier", "CAT_TECHNICAL": "Technique", "CAT_USE_CASE": "Cas d'utilisation",
    "CAT_TEST_REQUIREMENT": "Exigence de test", "CAT_UNDEFINED": "Non définie",
}
DECISIONS_LIB = {"retenu": "Retenu", "a-confirmer": "À confirmer", "non-retenu": "Non retenu"}
NIVEAUX_LIB = {"composant": "Composant", "integration-composants": "Intégration de composants", "systeme": "Système",
               "integration-systemes": "Intégration de systèmes", "acceptation": "Acceptation"}
APPROCHES_LIB = {"cas": "Cas de tests", "campagne-dediee": "Campagne dédiée", "checklist": "Checklist",
                 "exploratoire": "Sessions exploratoires"}
PRIORITES_LIB = {"haute": "Haute", "moyenne": "Moyenne", "basse": "Basse"}


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", t.replace("’", "'")).strip().lower()


def lib(table, code):
    return table.get(code, code or "")


def code(table, valeur):
    """Libellé ou code -> code. Valeur inconnue : renvoyée telle quelle (le contrôle la signalera)."""
    v = texte(valeur)
    if not v:
        return ""
    n = _norm(v)
    for k, l in table.items():
        if n in (_norm(k), _norm(l), _norm(l.split(" (")[0])):
            return k
    return v


def texte(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return "\n".join(l.rstrip() for l in str(v).replace("\r\n", "\n").split("\n")).strip()


def liste(v):
    if isinstance(v, list):
        return [texte(x) for x in v if texte(x)]
    return [x.strip() for x in re.split(r"[,;\n]", texte(v)) if x.strip()]


# ---------------------------------------------------------------- projection

CHAMPS_EX = ("id", "fonctionnalite", "titre", "description", "source", "criticite", "categorie", "questions")
CHAMPS_CT = ("id", "fonctionnalite", "titre", "exigences", "type", "type_test", "technique", "importance",
             "prerequis", "description", "jeux_de_donnees", "questions", "etapes")
CHAMPS_TT = ("id", "type_test", "decision", "niveau", "approche", "objectif", "exigences", "cas", "outil",
             "priorite", "justification", "questions")
LISTES = {"questions", "exigences", "jeux_de_donnees", "cas"}
DEFAUTS = {"criticite": "MAJOR", "categorie": "CAT_FUNCTIONAL", "importance": "MEDIUM"}


def _proj(obj, champs):
    r = {}
    for c in champs:
        if c == "etapes":
            r[c] = [{"action": texte(s.get("action")), "resultat_attendu": texte(s.get("resultat_attendu"))}
                    for s in obj.get("etapes") or []]
        elif c in LISTES:
            r[c] = liste(obj.get(c) or [])
        else:
            r[c] = texte(obj.get(c)) or DEFAUTS.get(c, "")
    return r


def projection(data):
    return {
        "exigences": [_proj(e, CHAMPS_EX) for e in data.get("exigences") or []],
        "cas": [_proj(c, CHAMPS_CT) for c in data.get("cas_de_tests") or []],
        "strategie": [_proj(t, CHAMPS_TT) for t in data.get("strategie_tests") or []],
    }


def differences(avant, apres):
    """Résumé lisible des différences entre deux projections."""
    res = []
    for cle, nom in (("exigences", "exigence"), ("cas", "cas"), ("strategie", "type de test")):
        a = {x["id"]: x for x in avant[cle] if x["id"]}
        b = {x["id"]: x for x in apres[cle] if x["id"]}
        nouveaux = [x for x in apres[cle] if not x["id"]]
        for i in b.keys() - a.keys():
            res.append(f"{nom} ajouté(e) : {i}")
        for x in nouveaux:
            res.append(f"{nom} ajouté(e) sans identifiant : « {x.get('titre') or x.get('type_test')} » (numéro attribué)")
        for i in a.keys() - b.keys():
            res.append(f"{nom} supprimé(e) : {i}")
        for i in a.keys() & b.keys():
            champs = [c for c in a[i] if a[i][c] != b[i][c]]
            if champs:
                res.append(f"{nom} modifié(e) : {i} ({', '.join(champs)})")
        if [x["id"] for x in avant[cle]] != [x["id"] for x in apres[cle] if x["id"]] and not res:
            res.append(f"ordre des {cle} modifié")
    return res


def _prochain(prefixe, largeur, existants):
    nums = [int(re.sub(r"\D", "", i)) for i in existants if re.sub(r"\D", "", i)]
    n = max(nums, default=0) + 1
    return f"{prefixe}{n:0{largeur}d}"


def appliquer(data, proj):
    """Reporte une projection (venue d'Excel ou de Word) dans le JSON, en conservant les autres champs."""
    def fusion(anciens, nouveaux, champs, prefixe, largeur):
        par_id = {x.get("id"): x for x in anciens}
        ids = {x["id"] for x in nouveaux if x["id"]} | set(par_id)
        res = []
        for n in nouveaux:
            if not n["id"]:
                n["id"] = _prochain(prefixe, largeur, ids)
                ids.add(n["id"])
            base = dict(par_id.get(n["id"], {}))
            for c in champs:
                v = n[c]
                if v in ("", []) and c != "etapes" and c not in ("id",):
                    base.pop(c, None)
                else:
                    base[c] = v
            res.append(base)
        return res

    data["exigences"] = fusion(data.get("exigences") or [], proj["exigences"], CHAMPS_EX, "EX-", 3)
    data["cas_de_tests"] = fusion(data.get("cas_de_tests") or [], proj["cas"], CHAMPS_CT, "CT", 4)
    data["strategie_tests"] = fusion(data.get("strategie_tests") or [], proj["strategie"], CHAMPS_TT, "TT-", 2)
    for c in data["cas_de_tests"]:
        if c.get("type_test") in TYPES_TEST:
            c["nature"] = TYPES_TEST[c["type_test"]][1]
    data.setdefault("meta", {})["version"] = int(data.get("meta", {}).get("version") or 0) + 1
    ordre = ["meta", "projet", "ranger_par_fonctionnalite", "strategie_tests", "exigences", "cas_de_tests"]
    return {**{k: data[k] for k in ordre if k in data}, **{k: v for k, v in data.items() if k not in ordre}}


# ---------------------------------------------------------------- Excel

COLS_CT = [("ID", 10), ("Fonctionnalité", 18), ("Titre", 36), ("Exigences", 12), ("Nature", 11),
           ("Type de test", 24), ("Technique ISTQB", 32), ("Importance", 12), ("Prérequis", 36), ("Objectif", 30),
           ("Jeux de données", 14), ("Questions", 12), ("N°", 5), ("Action", 45), ("Résultat attendu", 50)]
COLS_EX = [("ID", 9), ("Fonctionnalité", 20), ("Titre", 36), ("Description", 55), ("Source", 14),
           ("Criticité", 12), ("Catégorie", 18), ("Questions", 14)]
COLS_TT = [("ID", 7), ("Type de test", 30), ("Décision", 13), ("Niveau", 18), ("Approche", 18), ("Objectif", 40),
           ("Exigences", 16), ("Cas", 22), ("Outil", 20), ("Priorité", 10), ("Justification", 55), ("Questions", 12)]

LISEZMOI = [
    "Cas de tests — version modifiable",
    "",
    "Ce classeur est généré depuis cas-de-tests.json. Vous pouvez le modifier directement, puis demander à l'agent : /corriger <projet>",
    "L'agent reporte vos modifications dans le JSON, régénère le Word et la vue Markdown, puis lance le contrôle.",
    "",
    "Feuille « Cas de tests » : une ligne par étape.",
    "  - Les colonnes du cas (ID à Questions) se remplissent sur la PREMIÈRE ligne du cas.",
    "  - Ajouter une étape : insérer une ligne sous le cas, laisser ID à Questions vides, remplir Action et Résultat attendu.",
    "  - Ajouter un cas : nouvelle ligne avec un Titre ; laisser l'ID vide, l'agent attribue le numéro suivant.",
    "  - Supprimer un cas : supprimer toutes ses lignes. Un numéro supprimé n'est jamais réutilisé.",
    "  - Nature, Type de test, Technique ISTQB, Importance : choisir dans la liste déroulante.",
    "  - Exigences, Jeux de données, Questions : identifiants séparés par des virgules (EX-001, JDD-002, Q-003).",
    "  - La colonne N° est indicative : l'ordre des lignes fait foi.",
    "",
    "Feuilles « Exigences » et « Stratégie » : une ligne par élément, mêmes règles.",
    "",
    "À ne pas faire : modifier le Word et l'Excel en même temps (l'agent demandera lequel garder) ; renommer les feuilles ou les en-têtes ;",
    "modifier ce fichier une fois déplacé dans 03-valide (le remettre d'abord dans 02-a-valider).",
    "Fermer le fichier dans Excel avant de lancer /corriger.",
]


def _feuille(wb, titre, cols):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    ws = wb.create_sheet(titre)
    fin = Side(style="thin", color="BFBFBF")
    for i, (nom, larg) in enumerate(cols, start=1):
        c = ws.cell(1, i, nom)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        c.border = Border(top=fin, bottom=fin, left=fin, right=fin)
        ws.column_dimensions[c.column_letter].width = larg
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 30
    return ws


def _style_ligne(ws, r, ncol, couleur):
    from openpyxl.styles import Alignment, Border, PatternFill, Side
    fin = Side(style="thin", color="BFBFBF")
    for i in range(1, ncol + 1):
        c = ws.cell(r, i)
        c.alignment = Alignment(vertical="top", wrap_text=True)
        c.border = Border(top=fin, bottom=fin, left=fin, right=fin)
        if couleur:
            c.fill = PatternFill("solid", fgColor=couleur)


def _validation(ws, wb, col, libelles, nom, derniere):
    from openpyxl.worksheet.datavalidation import DataValidation
    lst = wb["Listes"]
    j = lst.max_column + 1 if lst.max_column > 1 or lst["A1"].value else 1
    lst.cell(1, j, nom)
    for i, l in enumerate(libelles, start=2):
        lst.cell(i, j, l)
    lettre = lst.cell(1, j).column_letter
    dv = DataValidation(type="list", formula1=f"=Listes!${lettre}$2:${lettre}${len(libelles) + 1}", allow_blank=True,
                        showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add(f"{col}2:{col}{max(derniere, 2) + 200}")


def ecrire_xlsx(data, projet_nom, chemin):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    lm = wb.active
    lm.title = "Lisez-moi"
    for i, l in enumerate(LISEZMOI, start=1):
        lm.cell(i, 1, l)
    lm["A1"].value = f"Cas de tests — {projet_nom} (version {data.get('meta', {}).get('version', '?')}) — version modifiable"
    lm["A1"].font = Font(bold=True, size=14)
    lm.column_dimensions["A"].width = 140
    listes = wb.create_sheet("Listes")

    ws = _feuille(wb, "Cas de tests", COLS_CT)
    r, alterne = 2, False
    for c in data.get("cas_de_tests") or []:
        alterne = not alterne
        couleur = "F2F7FC" if alterne else None
        etapes = c.get("etapes") or [{}]
        for k, s in enumerate(etapes, start=1):
            if k == 1:
                vals = [c.get("id"), c.get("fonctionnalite"), c.get("titre"), ", ".join(c.get("exigences") or []),
                        lib(NATURES, c.get("type")), lib(TYPES_TEST_LIB, c.get("type_test")),
                        lib(TECHNIQUES_LIB, c.get("technique")), lib(IMPORTANCES_LIB, c.get("importance") or "MEDIUM"),
                        c.get("prerequis"), c.get("description"), ", ".join(c.get("jeux_de_donnees") or []),
                        ", ".join(c.get("questions") or [])]
            else:
                vals = [None] * 12
            vals += [k, s.get("action"), s.get("resultat_attendu")]
            for i, v in enumerate(vals, start=1):
                ws.cell(r, i, v if v not in ("",) else None)
            _style_ligne(ws, r, len(COLS_CT), couleur)
            if k == 1:
                ws.cell(r, 1).font = Font(bold=True)
            r += 1
    ws.auto_filter.ref = f"A1:{ws.cell(1, len(COLS_CT)).column_letter}{max(r - 1, 1)}"
    for col, table, nom in (("E", NATURES, "Nature"), ("F", TYPES_TEST_LIB, "Type de test"),
                            ("G", TECHNIQUES_LIB, "Technique ISTQB"), ("H", IMPORTANCES_LIB, "Importance")):
        _validation(ws, wb, col, list(table.values()), nom, r)

    we = _feuille(wb, "Exigences", COLS_EX)
    for r, e in enumerate(data.get("exigences") or [], start=2):
        vals = [e.get("id"), e.get("fonctionnalite"), e.get("titre"), e.get("description"), e.get("source"),
                lib(CRITICITES_LIB, e.get("criticite") or "MAJOR"), lib(CATEGORIES_LIB, e.get("categorie") or "CAT_FUNCTIONAL"),
                ", ".join(e.get("questions") or [])]
        for i, v in enumerate(vals, start=1):
            we.cell(r, i, v or None)
        _style_ligne(we, r, len(COLS_EX), None)
    n = len(data.get("exigences") or []) + 1
    _validation(we, wb, "F", list(CRITICITES_LIB.values()), "Criticité", n)
    _validation(we, wb, "G", list(CATEGORIES_LIB.values()), "Catégorie", n)

    wt = _feuille(wb, "Stratégie", COLS_TT)
    for r, t in enumerate(data.get("strategie_tests") or [], start=2):
        vals = [t.get("id"), lib(TYPES_STRAT_LIB, t.get("type_test")), lib(DECISIONS_LIB, t.get("decision")),
                lib(NIVEAUX_LIB, t.get("niveau")), lib(APPROCHES_LIB, t.get("approche")), t.get("objectif"),
                ", ".join(t.get("exigences") or []), ", ".join(t.get("cas") or []), t.get("outil"),
                lib(PRIORITES_LIB, t.get("priorite")), t.get("justification"), ", ".join(t.get("questions") or [])]
        for i, v in enumerate(vals, start=1):
            wt.cell(r, i, v or None)
        _style_ligne(wt, r, len(COLS_TT), None)
    n = len(data.get("strategie_tests") or []) + 1
    for col, table, nom in (("B", TYPES_STRAT_LIB, "Type de test (stratégie)"), ("C", DECISIONS_LIB, "Décision"),
                            ("D", NIVEAUX_LIB, "Niveau"), ("E", APPROCHES_LIB, "Approche"), ("J", PRIORITES_LIB, "Priorité")):
        _validation(wt, wb, col, list(table.values()), nom, n)

    listes.sheet_state = "hidden"
    wb.move_sheet("Listes", offset=10)
    wb.active = 1
    wb.save(chemin)


def _entetes_ok(ws, cols, chemin):
    lus = [texte(ws.cell(1, i).value) for i in range(1, len(cols) + 1)]
    if [_norm(x) for x in lus] != [_norm(c[0]) for c in cols]:
        raise ValueError(f"{chemin.name}, feuille « {ws.title} » : en-têtes modifiés ({', '.join(lus)}). "
                         f"Attendu : {', '.join(c[0] for c in cols)}")


def lire_xlsx(chemin):
    from openpyxl import load_workbook
    wb = load_workbook(chemin, data_only=True)
    for f in ("Cas de tests", "Exigences", "Stratégie"):
        if f not in wb.sheetnames:
            raise ValueError(f"{chemin.name} : feuille « {f} » absente (feuilles : {', '.join(wb.sheetnames)})")
    ws = wb["Cas de tests"]
    _entetes_ok(ws, COLS_CT, chemin)
    cas, courant = [], None
    for ligne in ws.iter_rows(min_row=2, max_col=len(COLS_CT), values_only=True):
        v = [texte(x) for x in ligne]
        if not any(v):
            continue
        entete = v[:12]
        action, resultat = v[13], v[14]
        nouveau = any(entete[1:12]) or (entete[0] and (courant is None or entete[0] != courant["id"]))
        if nouveau:
            courant = {"id": entete[0], "fonctionnalite": entete[1], "titre": entete[2], "exigences": liste(entete[3]),
                       "type": code(NATURES, entete[4]), "type_test": code(TYPES_TEST_LIB, entete[5]),
                       "technique": code(TECHNIQUES_LIB, entete[6]),
                       "importance": code(IMPORTANCES_LIB, entete[7]) or "MEDIUM",
                       "prerequis": entete[8], "description": entete[9], "jeux_de_donnees": liste(entete[10]),
                       "questions": liste(entete[11]), "etapes": []}
            cas.append(courant)
        elif courant is None:
            raise ValueError(f"{chemin.name} : une étape (ligne « {action[:40]} ») précède le premier cas")
        if action or resultat:
            courant["etapes"].append({"action": action, "resultat_attendu": resultat})

    we = wb["Exigences"]
    _entetes_ok(we, COLS_EX, chemin)
    exigences = []
    for ligne in we.iter_rows(min_row=2, max_col=len(COLS_EX), values_only=True):
        v = [texte(x) for x in ligne]
        if any(v):
            exigences.append({"id": v[0], "fonctionnalite": v[1], "titre": v[2], "description": v[3], "source": v[4],
                              "criticite": code(CRITICITES_LIB, v[5]) or "MAJOR",
                              "categorie": code(CATEGORIES_LIB, v[6]) or "CAT_FUNCTIONAL", "questions": liste(v[7])})

    wt = wb["Stratégie"]
    _entetes_ok(wt, COLS_TT, chemin)
    strategie = []
    for ligne in wt.iter_rows(min_row=2, max_col=len(COLS_TT), values_only=True):
        v = [texte(x) for x in ligne]
        if any(v):
            strategie.append({"id": v[0], "type_test": code(TYPES_STRAT_LIB, v[1]), "decision": code(DECISIONS_LIB, v[2]),
                              "niveau": code(NIVEAUX_LIB, v[3]), "approche": code(APPROCHES_LIB, v[4]), "objectif": v[5],
                              "exigences": liste(v[6]), "cas": liste(v[7]), "outil": v[8],
                              "priorite": code(PRIORITES_LIB, v[9]), "justification": v[10], "questions": liste(v[11])})
    return {"exigences": [_proj(x, CHAMPS_EX) for x in exigences], "cas": [_proj(x, CHAMPS_CT) for x in cas],
            "strategie": [_proj(x, CHAMPS_TT) for x in strategie]}


# ---------------------------------------------------------------- Word

CHAMPS_FICHE = [("Fonctionnalité", "fonctionnalite"), ("Exigences", "exigences"), ("Nature", "type"),
                ("Type de test", "type_test"), ("Technique ISTQB", "technique"), ("Importance", "importance"),
                ("Prérequis", "prerequis"), ("Objectif", "description"), ("Jeux de données", "jeux_de_donnees"),
                ("Questions", "questions")]
RE_TITRE_CAS = re.compile(r"^\s*(CT\d{4,})?\s*[—–-]?\s*(.*)$")


def _ombrer(cellule, couleur):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc = cellule._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), couleur)
    tc.append(shd)


def _cellule(c, valeur, gras=False):
    lignes = texte(valeur).split("\n") if texte(valeur) else [""]
    p = c.paragraphs[0]
    for i, l in enumerate(lignes):
        if i:
            p = c.add_paragraph()
        run = p.add_run(l)
        run.bold = gras


def _tableau(doc, entetes, lignes, largeurs=None):
    from docx.oxml.ns import qn
    from docx.shared import Cm
    t = doc.add_table(rows=1, cols=len(entetes))
    t.style = "Table Grid"
    for i, h in enumerate(entetes):
        _cellule(t.rows[0].cells[i], h, gras=True)
        _ombrer(t.rows[0].cells[i], "D9E2F3")
    for ligne in lignes:
        cells = t.add_row().cells
        for i, v in enumerate(ligne):
            _cellule(cells[i], v)
    if largeurs:
        t.autofit = False
        grille = t._tbl.tblGrid
        for i, col in enumerate(grille.findall(qn("w:gridCol"))):
            col.set(qn("w:w"), str(int(Cm(largeurs[i]).twips)))
        for row in t.rows:
            for i, w in enumerate(largeurs):
                row.cells[i].width = Cm(w)
    return t


def ecrire_docx(data, projet_nom, chemin):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt
    doc = Document()
    s = doc.sections[0]
    s.orientation = WD_ORIENT.LANDSCAPE
    s.page_width, s.page_height = Cm(29.7), Cm(21.0)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(s, m, Cm(1.5))
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(9.5)

    doc.add_heading(f"Cas de tests — {projet_nom} (version {data.get('meta', {}).get('version', '?')})", 0)
    for l in ("Document modifiable, généré depuis cas-de-tests.json. Après vos modifications, demandez à l'agent : "
              "/corriger <projet>. Il reporte les modifications dans le JSON et régénère l'Excel et la vue Markdown.",
              "Règles : modifier le contenu des tableaux ; ne pas renommer les titres de colonnes ni la première colonne "
              "des fiches. Ajouter un cas : copier un bloc complet (titre + fiche + étapes) et laisser « CTxxxx » à la place "
              "du numéro, l'agent attribuera le suivant. Supprimer un cas : supprimer son bloc. Ajouter une étape : ajouter "
              "une ligne au tableau des étapes. Valeurs des listes (nature, type de test, technique, importance…) : celles "
              "de l'Excel ou de docs/TECHNIQUES-ISTQB.md. Accepter les modifications suivies et fermer Word avant /corriger."):
        doc.add_paragraph(l)

    doc.add_heading("Stratégie de types de tests", 1)
    _tableau(doc, [c[0] for c in COLS_TT], [
        [t.get("id"), lib(TYPES_STRAT_LIB, t.get("type_test")), lib(DECISIONS_LIB, t.get("decision")),
         lib(NIVEAUX_LIB, t.get("niveau")), lib(APPROCHES_LIB, t.get("approche")), t.get("objectif"),
         ", ".join(t.get("exigences") or []), ", ".join(t.get("cas") or []), t.get("outil"),
         lib(PRIORITES_LIB, t.get("priorite")), t.get("justification"), ", ".join(t.get("questions") or [])]
        for t in data.get("strategie_tests") or []],
        [1.2, 2.6, 1.8, 1.8, 2, 3.6, 2.4, 2.2, 2.4, 1.5, 3.5, 1.8])

    doc.add_heading("Exigences", 1)
    _tableau(doc, [c[0] for c in COLS_EX], [
        [e.get("id"), e.get("fonctionnalite"), e.get("titre"), e.get("description"), e.get("source"),
         lib(CRITICITES_LIB, e.get("criticite") or "MAJOR"), lib(CATEGORIES_LIB, e.get("categorie") or "CAT_FUNCTIONAL"),
         ", ".join(e.get("questions") or [])] for e in data.get("exigences") or []],
        [1.6, 2.6, 4, 7.5, 2, 2, 2.4, 2])

    doc.add_heading("Cas de tests", 1)
    fonction = None
    for c in data.get("cas_de_tests") or []:
        if c.get("fonctionnalite") != fonction:
            fonction = c.get("fonctionnalite")
            doc.add_heading(fonction or "Sans fonctionnalité", 2)
        doc.add_heading(f"{c.get('id')} — {c.get('titre', '')}", 3)
        valeurs = {"fonctionnalite": c.get("fonctionnalite"), "exigences": ", ".join(c.get("exigences") or []),
                   "type": lib(NATURES, c.get("type")), "type_test": lib(TYPES_TEST_LIB, c.get("type_test")),
                   "technique": lib(TECHNIQUES_LIB, c.get("technique")),
                   "importance": lib(IMPORTANCES_LIB, c.get("importance") or "MEDIUM"),
                   "prerequis": c.get("prerequis"), "description": c.get("description"),
                   "jeux_de_donnees": ", ".join(c.get("jeux_de_donnees") or []),
                   "questions": ", ".join(c.get("questions") or [])}
        t = _tableau(doc, ["Champ", "Valeur"], [[l, valeurs[k]] for l, k in CHAMPS_FICHE], [4, 22.6])
        for row in t.rows[1:]:
            _ombrer(row.cells[0], "F2F2F2")
        doc.add_paragraph()
        _tableau(doc, ["N°", "Action", "Résultat attendu"],
                 [[i, s.get("action"), s.get("resultat_attendu")] for i, s in enumerate(c.get("etapes") or [], start=1)],
                 [1.2, 12.7, 12.7])
    doc.save(chemin)


def _texte_cellule(c):
    return texte("\n".join(p.text for p in c.paragraphs))


def lire_docx(chemin):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(chemin)
    xml = doc.element.body.xml
    if "<w:ins " in xml or "<w:del " in xml:
        raise ValueError(f"{chemin.name} contient des modifications suivies : les accepter (Révision > Accepter tout), "
                         "enregistrer et fermer Word, puis relancer")
    ent_tt = [_norm(c[0]) for c in COLS_TT]
    ent_ex = [_norm(c[0]) for c in COLS_EX]
    fiche = {_norm(l): k for l, k in CHAMPS_FICHE}
    exigences, strategie, cas = [], [], []
    courant = None
    for el in doc.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(el, doc)
            style = _norm(p.style.name if p.style is not None else "")
            t = texte(p.text)
            if t and (style.startswith(("heading 3", "titre 3")) or re.match(r"^CT\d{4,}\s*[—–-]", t)):
                m = re.match(r"^\s*CTx{2,}\s*[—–-]\s*(.*)$", t, flags=re.I)
                if m:
                    ident, titre = "", m.group(1).strip()
                else:
                    m = RE_TITRE_CAS.match(t)
                    ident, titre = m.group(1) or "", m.group(2).strip()
                courant = {"id": ident, "titre": titre, "etapes": [], "_fiche": False}
                cas.append(courant)
            continue
        if tag != "tbl":
            continue
        tb = Table(el, doc)
        lignes = [[_texte_cellule(c) for c in r.cells] for r in tb.rows]
        if not lignes:
            continue
        entete = [_norm(x) for x in lignes[0]]
        if entete == ent_tt:
            for v in lignes[1:]:
                if any(v):
                    strategie.append({"id": v[0], "type_test": code(TYPES_STRAT_LIB, v[1]), "decision": code(DECISIONS_LIB, v[2]),
                                      "niveau": code(NIVEAUX_LIB, v[3]), "approche": code(APPROCHES_LIB, v[4]),
                                      "objectif": v[5], "exigences": liste(v[6]), "cas": liste(v[7]), "outil": v[8],
                                      "priorite": code(PRIORITES_LIB, v[9]), "justification": v[10], "questions": liste(v[11])})
        elif entete == ent_ex:
            for v in lignes[1:]:
                if any(v):
                    exigences.append({"id": v[0], "fonctionnalite": v[1], "titre": v[2], "description": v[3], "source": v[4],
                                      "criticite": code(CRITICITES_LIB, v[5]) or "MAJOR",
                                      "categorie": code(CATEGORIES_LIB, v[6]) or "CAT_FUNCTIONAL", "questions": liste(v[7])})
        elif entete[:2] == ["champ", "valeur"]:
            if courant is None:
                raise ValueError(f"{chemin.name} : une fiche de cas n'a pas de titre « CT0001 — Titre » au-dessus")
            for v in lignes[1:]:
                k = fiche.get(_norm(v[0]))
                if k:
                    courant[k] = v[1] if len(v) > 1 else ""
            courant["_fiche"] = True
        elif entete and entete[0] in ("n°", "no", "n", "#"):
            if courant is None:
                raise ValueError(f"{chemin.name} : un tableau d'étapes n'a pas de titre de cas au-dessus")
            for v in lignes[1:]:
                if len(v) >= 3 and (v[1] or v[2]):
                    courant["etapes"].append({"action": v[1], "resultat_attendu": v[2]})
    res_cas = []
    for c in cas:
        if not c.pop("_fiche"):
            raise ValueError(f"{chemin.name} : le cas « {c['id'] or c['titre']} » n'a pas de fiche (tableau Champ / Valeur)")
        res_cas.append({"id": c["id"], "fonctionnalite": c.get("fonctionnalite", ""), "titre": c["titre"],
                        "exigences": liste(c.get("exigences", "")), "type": code(NATURES, c.get("type")),
                        "type_test": code(TYPES_TEST_LIB, c.get("type_test")),
                        "technique": code(TECHNIQUES_LIB, c.get("technique")),
                        "importance": code(IMPORTANCES_LIB, c.get("importance")) or "MEDIUM",
                        "prerequis": c.get("prerequis", ""), "description": c.get("description", ""),
                        "jeux_de_donnees": liste(c.get("jeux_de_donnees", "")), "questions": liste(c.get("questions", "")),
                        "etapes": c["etapes"]})
    return {"exigences": [_proj(x, CHAMPS_EX) for x in exigences], "cas": [_proj(x, CHAMPS_CT) for x in res_cas],
            "strategie": [_proj(x, CHAMPS_TT) for x in strategie]}
