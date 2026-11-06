# Module de contenu de build_manual.py pour l'application web : lit le contenu du manuel en JSON
# (écrit par l'assistant, contrôlé par outils/manuel.py) au lieu d'un module Python rédigé à la main.
# Chemin du JSON : variable QAF_CONTENU_MANUEL. Format : voir outils/manuel.py.
import json as _json
import os as _os

_c = _json.loads(open(_os.environ["QAF_CONTENU_MANUEL"], encoding="utf-8").read())
PROJET = (_c.get("projet") or "PROJET").upper()
MODULE = (_c.get("sous_titre") or "MANUEL D’UTILISATION").upper()
TITRE = _c.get("titre") or f"Manuel d’utilisation – {PROJET}"


def _t(texte):
    # [[…]] insère une image de bouton dans build_manual.py : non utilisé ici, neutralisé.
    return str(texte or "").replace("[[", "[​[")


def build(d):
    x, chapitres = [], 0
    for b in _c.get("blocs") or []:
        t = b.get("type")
        if t == "titre":
            niveau = int(b.get("niveau") or 1)
            if niveau == 1 and b.get("numerote") is False:
                x.append(d["H_UNNUM"](_t(b["texte"])))
            elif niveau == 1:
                chapitres += 1
                x.append(d["H"](0, _t(b["texte"]), page_break=chapitres > 1))
            else:
                x.append(d["H"](min(niveau, 3) - 1, _t(b["texte"])))
        elif t == "paragraphe":
            x.append(d["P"](_t(b["texte"])))
        elif t == "procedure":
            x.append(d["LABEL"](_t(b["texte"])))
        elif t == "etapes":
            x.append(d["STEPS"]([_t(e) for e in b["elements"]]))
        elif t == "liste":
            x.append(d["BULLETS"]([_t(e) for e in b["elements"]]))
        elif t == "capture":
            x.append(d["FIG"](b["fichier"][:-4], _t(b.get("legende"))))
        elif t == "note":
            x.append(d["NOTE"](_t(b.get("libelle") or "Remarque"), _t(b["texte"])))
    return "".join(x)
