# -*- coding: utf-8 -*-
"""Vérifie qu'un poste est prêt à utiliser QA Factory (Claude Code ou OpenCode).

Usage : python outils/verifier_installation.py

Aucun appel réseau : vérifie les programmes, la bibliothèque Python, les variables
d'environnement partagées par .mcp.json et opencode.json, et les fichiers du dépôt.
"""
import importlib.util
import json
import os
import shutil
import subprocess

from qa_commun import RACINE

OK, KO, AV = "OK  ", "KO  ", "INFO"
resultats = []


def ligne(etat, quoi, detail=""):
    resultats.append(etat)
    print(f"[{etat}] {quoi}" + (f" — {detail}" if detail else ""))


def version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, shell=os.name == "nt")
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return ""


def main():
    print("Programmes")
    for nom, cmd, obligatoire in (("Node.js", ["node", "--version"], True), ("npx", ["npx", "--version"], True),
                                  ("Pandoc (CDC en .docx)", ["pandoc", "--version"], False),
                                  ("Claude Code", ["claude", "--version"], False), ("OpenCode", ["opencode", "--version"], False)):
        if shutil.which(cmd[0]):
            ligne(OK, nom, version(cmd))
        else:
            ligne(KO if obligatoire else AV, nom, "introuvable" + ("" if obligatoire else " (facultatif)"))
    if not (shutil.which("claude") or shutil.which("opencode")):
        ligne(KO, "Agent", "installer Claude Code ou OpenCode")

    print("\nPython")
    ligne(OK if importlib.util.find_spec("openpyxl") else KO, "openpyxl", "" if importlib.util.find_spec("openpyxl") else "pip install openpyxl")

    print("\nVariables d'environnement (lues par .mcp.json et opencode.json)")
    index = os.environ.get("SQUASH_MCP_INDEX", "")
    if not index:
        ligne(KO, "SQUASH_MCP_INDEX", "chemin de squash-tm-mcp\\dist\\index.js")
    elif not os.path.isfile(index):
        ligne(KO, "SQUASH_MCP_INDEX", f"fichier introuvable : {index} (lancer npm install puis npm run build dans squash-tm-mcp)")
    else:
        ligne(OK, "SQUASH_MCP_INDEX", index)
    url = os.environ.get("SQUASH_TM_BASE_URL", "")
    ligne(OK if url.endswith("/api/rest/latest") else KO, "SQUASH_TM_BASE_URL", url or "absente (doit finir par /api/rest/latest)")
    if os.environ.get("SQUASH_TM_API_TOKEN"):
        ligne(OK, "Authentification Squash", "jeton d'API (SQUASH_TM_API_TOKEN)")
    elif os.environ.get("SQUASH_TM_USERNAME") and os.environ.get("SQUASH_TM_PASSWORD"):
        ligne(OK, "Authentification Squash", f"identifiant et mot de passe ({os.environ['SQUASH_TM_USERNAME']})")
    else:
        ligne(KO, "Authentification Squash", "définir SQUASH_TM_API_TOKEN, ou SQUASH_TM_USERNAME et SQUASH_TM_PASSWORD "
              "si l'instance n'autorise pas les jetons (« Aucun secret JWT n'est défini »)")

    print("\nDépôt")
    for f in ("AGENTS.md", "CLAUDE.md", ".mcp.json", "opencode.json", ".claude/settings.json"):
        ligne(OK if (RACINE / f).exists() else KO, f)
    skills = sorted(p.parent.name for p in (RACINE / ".claude" / "skills").glob("*/SKILL.md"))
    ligne(OK if len(skills) >= 7 else KO, "skills", ", ".join(skills))
    cc = {p.name for p in (RACINE / ".claude" / "commands").glob("*.md")}
    oc = {p.name for p in (RACINE / ".opencode" / "commands").glob("*.md")}
    ligne(OK if cc == oc else KO, "commandes OpenCode synchronisées", "" if cc == oc else
          f"écarts : {', '.join(sorted(cc ^ oc))} → python outils/synchroniser_opencode.py")
    try:
        json.loads((RACINE / "opencode.json").read_text(encoding="utf-8"))
        ligne(OK, "opencode.json lisible")
    except Exception as e:
        ligne(KO, "opencode.json", str(e))

    n = resultats.count(KO)
    print(f"\nBilan : {n} point(s) bloquant(s)." + (" Poste prêt." if n == 0 else ""))


if __name__ == "__main__":
    main()
