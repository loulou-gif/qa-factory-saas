# -*- coding: utf-8 -*-
"""Manuel utilisateur au modèle Word d'une entreprise (déposé dans l'application, page Paramètres).

Usage : python outils/manuel_modele.py analyser <modele.docx>
        python outils/manuel_modele.py generer <modele.docx> <contenu.json> <captures/> <sortie.docx>

Le modèle est un document .docx ordinaire, rien à programmer. QA Factory en garde tout (couverture,
en-têtes et pieds de page, styles, marges) et y écrit le contenu du manuel :
- à l'emplacement d'un paragraphe ne contenant que {{CONTENU}} ; à défaut, à la fin du document ;
- {{SOMMAIRE}} (paragraphe seul) : sommaire automatique, actualisé par Word à l'ouverture ;
- marqueurs remplacés partout, en-têtes et pieds de page compris : {{PROJET}}, {{TITRE}}, {{SOUS_TITRE}},
  {{VERSION}}, {{DATE}}, {{AUTEUR}}, {{CLIENT}}, {{URL}} ;
- titres écrits avec les styles de titre du modèle (Titre 1, 2, 3), légendes avec son style Légende.

Le modèle n'est jamais exécuté : documents à macros (.docm) refusés.
"""
import argparse
import io
import json
import re
import struct
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

TAILLE_MAX = 25 * 1024 * 1024
DECOMPRESSE_MAX = 200 * 1024 * 1024
MARQUEURS = ("PROJET", "TITRE", "SOUS_TITRE", "VERSION", "DATE", "AUTEUR", "CLIENT", "URL")
RE_MARQUEUR = re.compile(r"\{\{\s*([A-Z_]+)\s*\}\}")
RE_PARA = re.compile(r"<w:p[ >].*?</w:p>", re.S)
RE_T = re.compile(r"(<w:t(?: [^>]*)?>)([^<]*)(</w:t>)")
EMU_CM = 360000
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TYPE_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


class ErreurModele(Exception):
    pass


def ouvrir(source) -> zipfile.ZipFile:
    donnees = Path(source).read_bytes() if not isinstance(source, (bytes, bytearray)) else bytes(source)
    if len(donnees) > TAILLE_MAX:
        raise ErreurModele(f"Fichier trop volumineux ({len(donnees) // (1024 * 1024)} Mo, {TAILLE_MAX // (1024 * 1024)} Mo au plus).")
    try:
        z = zipfile.ZipFile(io.BytesIO(donnees))
    except zipfile.BadZipFile:
        raise ErreurModele("Ce fichier n'est pas un document Word .docx (les anciens .doc sont à réenregistrer en .docx).")
    noms = z.namelist()
    if "word/document.xml" not in noms:
        raise ErreurModele("Ce fichier n'est pas un document Word .docx.")
    if any(n.lower().endswith("vbaproject.bin") for n in noms):
        raise ErreurModele("Le modèle contient des macros : l'enregistrer en document sans macro (.docx).")
    if sum(i.file_size for i in z.infolist()) > DECOMPRESSE_MAX:
        raise ErreurModele("Document trop volumineux une fois décompressé.")
    return z


def texte_para(p: str) -> str:
    return "".join(m.group(2) for m in RE_T.finditer(p))


def styles(z) -> dict:
    """Identifiants des styles utiles du modèle, d'après leur nom interne (indépendant de la langue de Word)."""
    try:
        xml = z.read("word/styles.xml").decode("utf8")
    except KeyError:
        return {}
    res = {}
    for m in re.finditer(r'<w:style\b[^>]*w:type="paragraph"[^>]*>.*?</w:style>', xml, re.S):
        bloc = m.group(0)
        sid = re.search(r'w:styleId="([^"]+)"', bloc)
        nom = re.search(r'<w:name w:val="([^"]+)"', bloc)
        if sid and nom:
            n = nom.group(1).lower()
            for cle in ("heading 1", "heading 2", "heading 3", "caption", "list paragraph", "toc heading", "title", "subtitle"):
                if n == cle:
                    res.setdefault(cle, sid.group(1))
    return res


def analyser(source) -> dict:
    z = ouvrir(source)
    doc = z.read("word/document.xml").decode("utf8")
    paras = [texte_para(p).strip() for p in RE_PARA.findall(doc)]
    st = styles(z)
    presents = []
    for n in z.namelist():
        if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n):
            for p in RE_PARA.findall(z.read(n).decode("utf8")):
                for m in RE_MARQUEUR.findall(texte_para(p)):
                    if m not in presents:
                        presents.append(m)
    avert = []
    titres = [k for k in ("heading 1", "heading 2", "heading 3") if k in st]
    if len(titres) < 3:
        avert.append("Styles de titre manquants (" + ", ".join(k.replace("heading ", "Titre ") for k in ("heading 1", "heading 2", "heading 3") if k not in st)
                     + ") : les titres concernés seront mis en gras, sans entrer dans le sommaire.")
    emplacement = "marqueur" if "{{CONTENU}}" in paras else "fin"
    if emplacement == "fin":
        avert.append("Pas de paragraphe {{CONTENU}} : le manuel sera écrit à la fin du document, après le contenu du modèle.")
    inconnus = [m for m in presents if m not in MARQUEURS + ("CONTENU", "SOMMAIRE")]
    if inconnus:
        avert.append("Marqueurs non reconnus, laissés tels quels : " + ", ".join("{{" + m + "}}" for m in inconnus) + ".")
    return {"emplacement": emplacement, "sommaire": "{{SOMMAIRE}}" in paras, "titres": len(titres),
            "legende": "caption" in st, "marqueurs": [m for m in presents if m in MARQUEURS],
            "paragraphes": len([p for p in paras if p]), "avertissements": avert}


# ---------------------------------------------------------------- écriture

def runs(texte: str, rpr: str = "") -> str:
    """**gras** et *italique* ; le reste en texte brut."""
    out = []
    for tok in re.split(r"(\*\*.+?\*\*|\*.+?\*)", str(texte or "")):
        if not tok:
            continue
        r = rpr
        if tok.startswith("**") and len(tok) > 4:
            tok, r = tok[2:-2], r + "<w:b/>"
        elif tok.startswith("*") and len(tok) > 2:
            tok, r = tok[1:-1], r + "<w:i/>"
        out.append(f'<w:r>{"<w:rPr>" + r + "</w:rPr>" if r else ""}<w:t xml:space="preserve">{escape(tok)}</w:t></w:r>')
    return "".join(out)


def para(inner: str, ppr: str = "") -> str:
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{inner}</w:p>"


def taille_png(chemin: Path) -> tuple:
    with open(chemin, "rb") as f:
        tete = f.read(24)
    if tete[:8] != b"\x89PNG\r\n\x1a\n":
        raise ErreurModele(f"{chemin.name} n'est pas une image PNG.")
    return struct.unpack(">II", tete[16:24])


def largeur_utile_cm(doc: str) -> float:
    m = re.search(r'<w:pgSz[^>]*w:w="(\d+)"', doc)
    g = re.search(r'<w:pgMar[^>]*w:left="(\d+)"', doc)
    d = re.search(r'<w:pgMar[^>]*w:right="(\d+)"', doc)
    if not m:
        return 16.0
    twips = int(m.group(1)) - int(g.group(1) if g else 1440) - int(d.group(1) if d else 1440)
    return max(8.0, min(17.0, twips / 567.0))


class Redacteur:
    def __init__(self, st: dict, captures: Path, largeur_cm: float):
        self.st, self.captures, self.largeur = st, captures, largeur_cm
        self.medias = {}   # nom de fichier -> (rId, cible)
        self.ids = iter(range(7000, 999999))
        self.figure = 0
        self.etape = 0

    def titre(self, niveau: int, texte: str) -> str:
        self.etape = 0
        sid = self.st.get(f"heading {min(max(niveau, 1), 3)}")
        if sid:
            return para(runs(texte), f'<w:pStyle w:val="{sid}"/>')
        taille = {1: 32, 2: 28}.get(niveau, 24)
        return para(runs(texte, f'<w:b/><w:sz w:val="{taille}"/>'), '<w:keepNext/><w:spacing w:before="240" w:after="120"/>')

    def image(self, fichier: str, legende: str) -> str:
        chemin = self.captures / fichier
        w, h = taille_png(chemin)
        cx = int(min(self.largeur, 16.0) * EMU_CM)
        cy = int(cx * h / max(w, 1))
        if cy > 20 * EMU_CM:  # capture très haute : limitée à 20 cm de haut
            cy = 20 * EMU_CM
            cx = int(cy * w / max(h, 1))
        if fichier not in self.medias:
            self.medias[fichier] = (f"rIdQaf{len(self.medias) + 1}", f"media/qaf_{len(self.medias) + 1}.png")
        rid = self.medias[fichier][0]
        did = next(self.ids)
        dessin = (f'<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:inline xmlns:wp="{NS_WP}" distT="0" distB="0" distL="0" distR="0">'
                  f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{did}" name="Capture {did}" descr="{escape(legende or fichier)}"/>'
                  f'<a:graphic xmlns:a="{NS_A}"><a:graphicData uri="{NS_PIC}"><pic:pic xmlns:pic="{NS_PIC}">'
                  f'<pic:nvPicPr><pic:cNvPr id="{did}" name="{escape(fichier)}"/><pic:cNvPicPr/></pic:nvPicPr>'
                  f'<pic:blipFill><a:blip xmlns:r="{NS_R}" r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                  f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                  f'<a:ln w="6350"><a:solidFill><a:srgbClr val="BFBFBF"/></a:solidFill></a:ln></pic:spPr></pic:pic></a:graphicData></a:graphic>'
                  f'</wp:inline></w:drawing></w:r>')
        self.figure += 1
        cap = self.st.get("caption")
        leg = para(runs(f"Figure {self.figure} – {legende}" if legende else f"Figure {self.figure}", "" if cap else "<w:i/>"),
                   (f'<w:pStyle w:val="{cap}"/>' if cap else "") + '<w:jc w:val="center"/>')
        return para(dessin, '<w:keepNext/><w:spacing w:before="120" w:after="60"/><w:jc w:val="center"/>') + leg

    def bloc(self, b: dict) -> str:
        t = b.get("type")
        if t == "titre":
            return self.titre(int(b.get("niveau") or 1), b["texte"])
        if t == "paragraphe":
            return para(runs(b["texte"]), '<w:jc w:val="both"/>')
        if t == "procedure":
            self.etape = 0
            return para(runs(b["texte"], "<w:b/>"), '<w:keepNext/><w:spacing w:before="160" w:after="80"/>')
        if t == "etapes":
            x = []
            for e in b["elements"]:
                self.etape += 1
                x.append(para(runs(f"{self.etape}. ") + runs(e), '<w:ind w:left="720" w:hanging="360"/><w:spacing w:after="80"/>'))
            return "".join(x)
        if t == "liste":
            return "".join(para(runs("• ") + runs(e), '<w:ind w:left="720" w:hanging="360"/><w:spacing w:after="60"/>')
                           for e in b["elements"])
        if t == "capture":
            return self.image(b["fichier"], b.get("legende") or "")
        if t == "note":
            ppr = ('<w:pBdr><w:left w:val="single" w:sz="24" w:space="8" w:color="808080"/></w:pBdr>'
                   '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:before="120" w:after="200"/><w:ind w:left="240"/>')
            return para(runs(f"**{b.get('libelle') or 'Remarque'}** : ") + runs(b["texte"]), ppr)
        return ""


def sommaire() -> str:
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>Sommaire : accepter sa mise à jour à l\'ouverture du document '
            '(ou clic droit, Mettre à jour les champs).</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def remplacer_marqueurs(xml: str, valeurs: dict) -> str:
    """Marqueurs d'un paragraphe, même répartis par Word sur plusieurs morceaux de texte."""
    def para_(m):
        p = m.group(0)
        txt = texte_para(p)
        if "{{" not in txt or not RE_MARQUEUR.search(txt):
            return p
        nouveau = RE_MARQUEUR.sub(lambda x: escape(valeurs[x.group(1)]) if x.group(1) in valeurs else x.group(0), txt)
        if nouveau == txt:
            return p
        premier = [True]

        def t_(mt):
            if premier[0]:
                premier[0] = False
                return '<w:t xml:space="preserve">' + nouveau + mt.group(3)
            return mt.group(1) + mt.group(3)
        return RE_T.sub(t_, p)
    return RE_PARA.sub(para_, xml)


def generer(modele, contenu: dict, captures: Path, sortie: Path, valeurs: dict) -> dict:
    z = ouvrir(modele)
    doc = z.read("word/document.xml").decode("utf8")
    st = styles(z)
    r = Redacteur(st, Path(captures), largeur_utile_cm(doc))
    corps = "".join(r.bloc(b) for b in contenu.get("blocs") or [])

    paras = list(RE_PARA.finditer(doc))
    cible = next((m for m in paras if texte_para(m.group(0)).strip() == "{{CONTENU}}"), None)
    toc = next((m for m in paras if texte_para(m.group(0)).strip() == "{{SOMMAIRE}}"), None)
    if cible:
        doc = doc[:cible.start()] + corps + doc[cible.end():]
    else:
        fin = doc.rfind("<w:sectPr")
        fin_corps = doc.rfind("</w:body>")
        pos = fin if fin != -1 and fin < fin_corps else fin_corps
        doc = doc[:pos] + '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' + corps + doc[pos:]
    if toc:
        doc = doc.replace(toc.group(0), sommaire(), 1)
    doc = remplacer_marqueurs(doc, valeurs)

    rels = z.read("word/_rels/document.xml.rels").decode("utf8")
    rels = rels.replace("</Relationships>", "".join(
        f'<Relationship Id="{rid}" Type="{TYPE_IMAGE}" Target="{cible_}"/>' for rid, cible_ in r.medias.values()) + "</Relationships>")
    types = z.read("[Content_Types].xml").decode("utf8")
    if not re.search(r"""Extension=["']png["']""", types, re.I):
        types = re.sub(r"(<Types[^>]*>)", r'\1<Default Extension="png" ContentType="image/png"/>', types, count=1)
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            n = item.filename
            data = z.read(n)
            if n == "word/document.xml":
                data = doc.encode("utf8")
            elif n == "word/_rels/document.xml.rels":
                data = rels.encode("utf8")
            elif n == "[Content_Types].xml":
                data = types.encode("utf8")
            elif re.match(r"word/(header|footer)\d*\.xml$", n):
                data = remplacer_marqueurs(data.decode("utf8"), valeurs).encode("utf8")
            elif n == "docProps/core.xml":
                c = data.decode("utf8")
                c = re.sub(r"<dc:title>.*?</dc:title>", "<dc:title>" + escape(valeurs.get("TITRE", "")) + "</dc:title>", c, flags=re.S)
                data = c.encode("utf8")
            elif n == "word/settings.xml" and toc:
                s = data.decode("utf8")
                if "<w:updateFields" not in s:
                    s = re.sub(r"(<w:settings[^>]*>)", r'\1<w:updateFields w:val="true"/>', s, count=1)
                data = s.encode("utf8")
            zo.writestr(item, data)
        for fichier, (rid, cible_) in r.medias.items():
            zo.write(Path(captures) / fichier, "word/" + cible_)
    return {"figures": r.figure, "emplacement": "marqueur" if cible else "fin", "sommaire": bool(toc)}


def valeurs_defaut(contenu: dict, fiche: dict) -> dict:
    conf = fiche.get("manuel") or {}
    nom = fiche.get("nom") or "Projet"
    inconnu = lambda v: v if v and "renseigner" not in str(v).lower() else "À renseigner"  # noqa: E731
    return {"PROJET": nom, "TITRE": contenu.get("titre") or f"Manuel d'utilisation – {nom}",
            "SOUS_TITRE": contenu.get("sous_titre") or "", "VERSION": conf.get("version") or "V1.0",
            "DATE": date.today().strftime("%d/%m/%Y"), "AUTEUR": inconnu(conf.get("auteur") or (fiche.get("cahier") or {}).get("auteur")),
            "CLIENT": inconnu(fiche.get("client")), "URL": (fiche.get("application") or {}).get("url") or "À renseigner"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="action", required=True)
    a1 = sp.add_parser("analyser")
    a1.add_argument("modele")
    a2 = sp.add_parser("generer")
    for n in ("modele", "contenu", "captures", "sortie"):
        a2.add_argument(n)
    a = p.parse_args()
    try:
        if a.action == "analyser":
            print(json.dumps(analyser(a.modele), ensure_ascii=False, indent=2))
        else:
            c = json.loads(Path(a.contenu).read_text(encoding="utf-8"))
            print(json.dumps(generer(a.modele, c, Path(a.captures), Path(a.sortie), valeurs_defaut(c, {})), ensure_ascii=False))
    except ErreurModele as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
