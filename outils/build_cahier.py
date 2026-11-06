# -*- coding: utf-8 -*-
"""Génère le cahier de tests Excel d'un projet à partir de 03-valide/cas-de-tests.json.

Usage : python outils/build_cahier.py <projet> [--nominaux] [--modele <modele.xlsx>] [--sans-exploration]

TEMPS B UNIQUEMENT : le script refuse de tourner tant que l'URL de la plateforme
(projet.json → application.url) n'est pas renseignée et que l'exploration n'a pas
été faite (04-livrables/exploration/decouvertes.md). Le cahier se produit en
parallèle de l'écriture des scripts automatisés.

Repris du générateur du projet Orange eFacture (OLIB) : le modèle
templates/cahier/modele_cahier.xlsx est copié tel quel (styles, en-tête, légende
des statuts, validations, mise en page) ; seule la zone « DETAILS DES TESTS » est
réécrite. Différence : le contenu vient du JSON validé (source unique), plus d'un
fichier Python écrit à la main.

- Identifiants : ceux du JSON (CT0001…), jamais renumérotés.
- RÉSULTAT, STATUT et COMMENTAIRE restent vides : ils sont remplis lors de la recette.
- --nominaux : ne garde que les cas de type « nominal » (cahier de recette client).
- Feuille « Traçabilité » : cas → exigences → nature, type de test et technique ISTQB → spec → test automatisé (s'il existe).
"""
import argparse
import io
import math
import zipfile
from copy import copy
from datetime import date

import openpyxl
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formatting.rule import Rule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.worksheet.datavalidation import DataValidation

from qa_commun import TECHNIQUES, TYPES_TEST, TEMPLATES, charger_cas, charger_projet, erreur, fonctionnalites, journaliser, slug

TEMPLATE = TEMPLATES / "cahier" / "modele_cahier.xlsx"
LOGO_SOURCE = TEMPLATES / "manuel" / "modele_manuel.docx"
FIRST_ROW = 32  # première ligne de la zone de détail du modèle (après l'en-tête ligne 31)
LINE_HEIGHT = 15.0
TYPES = {"nominal": "Nominal", "negatif": "Négatif", "limite": "Limite"}


def nature_cas(c):
    """« Négatif — Test de sécurité — Partitions d'équivalence (CTFL v4.0 §4.2.1) » pour la traçabilité."""
    tt = TYPES_TEST.get(c.get("type_test"), (c.get("type_test", ""),))[0]
    tech = TECHNIQUES.get(c.get("technique"))
    return " — ".join(x for x in (TYPES.get(c.get("type"), c.get("type", "")), tt,
                                   f"{tech[0]} ({tech[1]})" if tech else c.get("technique", "")) if x)


def lines_needed(text, width):
    if not text:
        return 1
    per_line = max(int(width * 1.15), 1)
    return sum(max(1, math.ceil(len(part) / per_line)) for part in str(text).split("\n"))


def logo_prestataire():
    if not LOGO_SOURCE.exists():
        return None
    try:
        with zipfile.ZipFile(LOGO_SOURCE) as docx:
            return io.BytesIO(docx.read("word/media/image1.png"))
    except (KeyError, zipfile.BadZipFile):
        return None


def sections_depuis_json(data, nominaux):
    cas = data.get("cas_de_tests", [])
    sections = []
    for f in fonctionnalites(data):
        lst = [c for c in cas if c.get("fonctionnalite") == f and (not nominaux or c.get("type") == "nominal")]
        if lst:
            sections.append((f.upper(), lst))
    return sections


def nom_fichier(projet, nominaux, ext="xlsx"):
    conf = projet.get("cahier", {})
    suffixe = "_nominaux" if nominaux else ""
    return f"Cahier_de_tests_{slug(projet.get('nom') or 'projet').replace('-', '_')}_{conf.get('version', 'V1.0')}{suffixe}.{ext}"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("projet")
    p.add_argument("--nominaux", action="store_true", help="ne garder que les parcours nominaux")
    p.add_argument("--modele", help="modèle Excel de l'entreprise (outils/cahier_modele.py) au lieu du modèle interne")
    p.add_argument("--sans-exploration", action="store_true",
                   help="application web : les cas validés suffisent (l'exploration n'est pas un préalable)")
    a = p.parse_args()

    d, projet = charger_projet(a.projet)
    if not a.sans_exploration:
        if not (projet.get("application", {}).get("url") or "").strip():
            erreur("temps B uniquement : renseigner projet.json → application.url (lien de la plateforme à tester)")
        if not (d / "04-livrables" / "exploration" / "decouvertes.md").exists():
            erreur("temps B uniquement : l'application n'a pas encore été explorée "
                   "(04-livrables/exploration/decouvertes.md absent). Lancer /explorer d'abord.")
    if a.modele:
        import cahier_modele
        try:
            out, n = cahier_modele.generer(a.projet, a.modele, nominaux=a.nominaux)
        except cahier_modele.ErreurModele as e:
            erreur(str(e))
        print(f"{out} : {n} cas de tests (modèle de l'entreprise)")
        return
    generer(a.projet, a.nominaux)


def generer(code, nominaux=False):
    """Cahier au modèle interne (templates/cahier/modele_cahier.xlsx) ; renvoie (fichier, nombre de cas)."""
    d, projet = charger_projet(code)
    data = charger_cas(d / "03-valide" / "cas-de-tests.json")
    if not TEMPLATE.exists():
        erreur(f"modèle introuvable : {TEMPLATE}")
    conf = projet.get("cahier", {})
    nominaux = nominaux or conf.get("nominaux_uniquement", False)
    sections = sections_depuis_json(data, nominaux)
    if not sections:
        erreur("aucun cas de test à écrire")

    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["Sheet1"]
    widths = {col: ws.column_dimensions[col].width for col in "ABCDEGHIJ"}
    widths["F"] = widths["E"]  # E et F partagent la même définition de colonne dans le modèle

    proto = {k: ws[c] for k, c in (("A", "A34"), ("B", "B35"), ("C", "C35"), ("D", "D35"), ("E", "E35"),
                                   ("F", "F35"), ("G", "G35"), ("H", "H34"), ("I", "I35"), ("J", "J35"))}
    proto = {k: (copy(c.font), copy(c.fill), copy(c.border), copy(c.alignment), c.number_format) for k, c in proto.items()}
    sep = ws["A73"]
    separator_style = (copy(sep.font), copy(sep.fill), copy(sep.border), copy(sep.alignment))

    # --- Zone de détail : effacement des données, fusions, images et hauteurs du modèle
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= FIRST_ROW:
            ws.unmerge_cells(str(rng))
    for row in range(FIRST_ROW, ws.max_row + 1):
        for col in range(1, 11):
            ws.cell(row, col).value = None
            ws.cell(row, col).style = "Normal"
        ws.row_dimensions[row].height = None
    ws._images = []

    # --- En-tête et métadonnées (valeurs inconnues : « À renseigner », jamais inventées)
    nom = projet.get("nom", code)
    app = projet.get("application", {})
    ws["A1"] = conf.get("titre") or f"CAHIER DE TESTS {nom.upper()}"
    ws["C15"] = nom.upper()
    ws.merge_cells("B16:E16")
    ws["B16"] = conf.get("description") or "À renseigner"
    ws.row_dimensions[16].height = 47.25
    ws["B17"] = app.get("url") or "À renseigner"
    ws.unmerge_cells("B18:B19")
    ws["B18"] = conf.get("contact") or "À renseigner"
    ws["B19"] = conf.get("auteur") or "À renseigner"
    for cell in ("B18", "B19"):
        ws[cell].font = copy(ws["B19"].font)
        ws[cell].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws["D20"] = date.today().strftime("%d/%m/%Y")
    ws["E20"] = f"Version: {conf.get('version', 'V1.0')}"
    ws["D21"] = "À renseigner"
    ws["E21"] = "Recette" if not nominaux else "Recette parties prenantes"
    for cell in ("D20", "D21"):
        ws[cell].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws["H31"] = "RÉSULTAT"
    ws["I31"] = "STATUT"

    img = logo_prestataire()
    if img:
        logo = Image(img)
        logo.height = 101
        logo.width = round(374 * 101 / 135)
        logo.anchor = OneCellAnchor(_from=AnchorMarker(col=5, colOff=1398920, row=4, rowOff=76712),
                                    ext=XDRPositiveSize2D(pixels_to_EMU(logo.width), pixels_to_EMU(logo.height)))
        ws.add_image(logo)

    def style(cell, col):
        font, fill, border, alignment, fmt = proto[col]
        cell.font, cell.fill, cell.border = copy(font), copy(fill), copy(border)
        cell.alignment, cell.number_format = copy(alignment), fmt

    def merge(col, top, bottom):
        if bottom > top:
            ws.merge_cells(f"{col}{top}:{col}{bottom}")
        for r in range(top, bottom + 1):
            style(ws[f"{col}{r}"], col)

    heights, trace = {}, []
    row, number = FIRST_ROW, 0
    for index, (feature, cases) in enumerate(sections):
        section_top = row
        for item in cases:
            number += 1
            steps = item.get("etapes", [])
            top, bottom = row, row + len(steps) - 1
            desc = item.get("titre", "")
            pre = item.get("prerequis", "")
            if item.get("jeux_de_donnees"):
                pre = f"{pre}\nJeux de données : {', '.join(item['jeux_de_donnees'])}"
            for col, value in (("B", item["id"]), ("C", pre), ("D", desc), ("J", None)):
                merge(col, top, bottom)
                ws[f"{col}{top}"] = value or None
            for i, s in enumerate(steps, start=1):
                r = top + i - 1
                style(ws[f"E{r}"], "E")
                ws[f"E{r}"] = f"{i}- {s.get('action', '')}"
                heights[r] = lines_needed(ws[f"E{r}"].value, widths["E"]) * LINE_HEIGHT
                for col, value in (("F", s.get("resultat_attendu")), ("G", "OK"), ("H", None), ("I", None)):
                    style(ws[f"{col}{r}"], col)
                    ws[f"{col}{r}"] = value
                need = lines_needed(s.get("resultat_attendu"), widths["F"]) * LINE_HEIGHT
                heights[r] = max(heights[r], need)
            for col, text in (("C", pre), ("D", desc)):
                need = lines_needed(text, widths[col]) * LINE_HEIGHT
                have = sum(heights[x] for x in range(top, bottom + 1))
                if have < need:
                    heights[bottom] += need - have
            auto = item.get("automatisation") or {}
            trace.append((item["id"], feature.replace("\n", " "), desc, ", ".join(item.get("exigences", [])),
                          nature_cas(item),
                          f"04-livrables/specs/{slug(item.get('fonctionnalite', ''))}.md",
                          auto.get("test", "—")))
            row = bottom + 1

        merge("A", section_top, row - 1)
        ws[f"A{section_top}"] = feature
        need = lines_needed(feature, widths["A"]) * LINE_HEIGHT
        have = sum(heights[x] for x in range(section_top, row))
        if have < need:
            heights[row - 1] += need - have
        if index < len(sections) - 1:
            ws.merge_cells(f"A{row}:J{row}")
            font, fill, border, alignment = separator_style
            ws[f"A{row}"].font, ws[f"A{row}"].fill = copy(font), copy(fill)
            ws[f"A{row}"].border, ws[f"A{row}"].alignment = copy(border), copy(alignment)
            row += 1

    last = row - 1
    for r, h in heights.items():
        ws.row_dimensions[r].height = round(h + 6, 2)

    # Validations OK / NOK (liste $B$24:$B$25 du modèle) sur STATUT ATTENDU et STATUT
    ws.data_validations.dataValidation = [dv for dv in ws.data_validations.dataValidation if dv.formula1 == '"OK,NOK"']
    status_list = DataValidation(type="list", formula1="$B$24:$B$25", allow_blank=True)
    status_list.add(f"G{FIRST_ROW}:G{last}")
    status_list.add(f"I{FIRST_ROW}:I{last}")
    ws.add_data_validation(status_list)

    # Mise en forme conditionnelle du modèle sur RÉSULTAT : NOK en rouge, OK en vert
    ws.conditional_formatting = ConditionalFormattingList()
    area = f"H{FIRST_ROW}:H{last}"
    for text, bg, fg in (("NOK", "FFFFC7CE", "FF9C0006"), ("OK", "FFC6EFCE", "FF006100")):
        rule = Rule(type="containsText", operator="containsText", text=text, stopIfTrue=True,
                    dxf=DifferentialStyle(font=Font(color=fg), fill=PatternFill(bgColor=bg, fill_type="solid")))
        rule.formula = [f'NOT(ISERROR(SEARCH("{text}",H{FIRST_ROW})))']
        ws.conditional_formatting.add(area, rule)

    # Feuille de traçabilité
    ts = wb.create_sheet("Traçabilité")
    header = ("ID", "FONCTIONNALITES", "DESCRIPTION", "EXIGENCES", "NATURE / TYPE DE TEST / TECHNIQUE ISTQB", "SPECIFICATION", "TEST AUTOMATISE")
    head_proto = ws["A31"]
    for c, value in enumerate(header, start=1):
        cell = ts.cell(1, c, value)
        cell.font, cell.fill = copy(head_proto.font), copy(head_proto.fill)
        cell.border, cell.alignment = copy(head_proto.border), copy(head_proto.alignment)
    for r, values in enumerate(trace, start=2):
        for c, value in enumerate(values, start=1):
            ts.cell(r, c, value).alignment = Alignment(vertical="center", wrap_text=True,
                                                       horizontal="center" if c == 1 else None)
    for col, width in zip("ABCDEFG", (10, 28, 45, 18, 40, 40, 50)):
        ts.column_dimensions[col].width = width
    ts.freeze_panes = "A2"
    ts.auto_filter.ref = f"A1:G{len(trace) + 1}"

    out_dir = d / "04-livrables" / "cahier"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / nom_fichier(projet, nominaux)
    wb.save(out)
    journaliser(d, "cahier", f"{number} cas", [str(out.relative_to(d))])
    print(f"{out} : {number} cas de tests, lignes {FIRST_ROW}-{last}")
    return out, number


if __name__ == "__main__":
    main()
