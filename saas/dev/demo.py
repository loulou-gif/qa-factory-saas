# -*- coding: utf-8 -*-
"""QA Factory SaaS sur un poste, en une commande, sans Docker.

Lance OpenCode en mode serveur et l'application web, puis ouvre le navigateur.
Fonctionne sous Windows, macOS et Linux.

    pip install -r saas/requirements.txt

    # Avec une clé OpenRouter (la clé est lue dans la variable OPENROUTER_API_KEY) :
    python saas/dev/demo.py --modele openrouter/anthropic/claude-sonnet-4.5

    # Avec un modèle gratuit d'OpenCode, sans clé (qualité moindre, offre limitée dans le temps) :
    python saas/dev/demo.py --modele opencode/deepseek-v4.1-flash-free

    # Démonstration sans IA (faux modèle qui rejoue l'analyse de SauceDemo) :
    python saas/dev/demo.py --simulation

    # Liste des modèles disponibles :  opencode models openrouter   |   opencode models opencode

Connexion : identifiant « demo », mot de passe « Demo-2026-qa » (à changer à la première connexion).
Les projets créés vont dans projets/ (ignoré par Git). Ctrl+C pour tout arrêter.

Squash : pour essayer l'envoi, définir avant le lancement SQUASH_MCP_DIR (dossier du MCP squash-tm
compilé), SQUASH_TM_BASE_URL et les identifiants, et utiliser un projet Squash d'essai.
"""
import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SAAS = RACINE / "saas"
# Le moteur n'utilise pas 4096 : c'est le port par défaut d'OpenCode, souvent déjà pris par OpenCode lui-même.
PORTS = {"modele": int(os.environ.get("QAF_PORT_MODELE", "4110")), "moteur": int(os.environ.get("QAF_PORT_MOTEUR", "4196")),
         "web": int(os.environ.get("QAF_PORT", "8000"))}


def libre(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def attendre(url, delai=90, auth=None):
    fin = time.time() + delai
    while time.time() < fin:
        try:
            req = urllib.request.Request(url)
            if auth:
                import base64
                req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modele", default=os.environ.get("QAF_MODELE", ""),
                   help="fournisseur/modèle, ex. openrouter/anthropic/claude-sonnet-4.5 ou opencode/deepseek-v4.1-flash-free")
    p.add_argument("--simulation", action="store_true", help="faux modèle de démonstration, sans IA")
    a = p.parse_args()
    modele = "simulation/demo" if a.simulation else a.modele.strip()
    if not modele:
        sys.exit("Choisir un modèle :\n"
                 "  python saas/dev/demo.py --modele openrouter/<fournisseur>/<modèle>   (clé dans OPENROUTER_API_KEY)\n"
                 "  python saas/dev/demo.py --modele opencode/deepseek-v4.1-flash-free   (gratuit, sans clé)\n"
                 "  python saas/dev/demo.py --simulation                                 (sans IA)")
    if modele.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Clé OpenRouter absente : définir la variable OPENROUTER_API_KEY (voir saas/README.md), puis relancer.")
    for nom, port in PORTS.items():
        if nom == "modele" and modele != "simulation/demo":
            continue
        if not libre(port):
            variable = {"web": "QAF_PORT", "moteur": "QAF_PORT_MOTEUR", "modele": "QAF_PORT_MODELE"}[nom]
            sys.exit(f"Le port {port} ({nom}) est déjà utilisé : arrêter la démo déjà lancée (Ctrl+C), "
                     f"ou choisir un autre port, ex. {variable}={port + 1} python saas/dev/demo.py ...")
    opencode = shutil.which("opencode")
    if not opencode:
        sys.exit("OpenCode introuvable : npm install -g opencode-ai")
    config = json.loads((SAAS / "opencode.serveur.json").read_text(encoding="utf-8"))
    if modele == "simulation/demo":
        config["provider"].update(json.loads((SAAS / "dev" / "opencode.simulation.json").read_text(encoding="utf-8"))["provider"])
    env = dict(os.environ)
    env.update({
        "QAF_RACINE": str(RACINE), "QAF_DONNEES": str(SAAS / "donnees-demo"), "QAF_MODELE": modele,
        "QAF_FAUX_MODELE_URL": f"http://127.0.0.1:{PORTS['modele']}/v1", "OPENCODE_URL": f"http://127.0.0.1:{PORTS['moteur']}",
        "OPENCODE_SERVER_PASSWORD": env.get("OPENCODE_SERVER_PASSWORD") or "demo-moteur", "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "QAF_ADMIN_IDENTIFIANT": "demo", "QAF_ADMIN_NOM": "Utilisateur démo", "QAF_ADMIN_MOT_DE_PASSE": "Demo-2026-qa",
        "PYTHONUNBUFFERED": "1",
    })
    env.setdefault("SQUASH_MCP_DIR", str(RACINE.parent / "squash-tm-mcp"))
    env.setdefault("SQUASH_TM_BASE_URL", "")
    procs = []
    try:
        if modele == "simulation/demo":
            procs.append(subprocess.Popen([sys.executable, str(SAAS / "dev" / "faux_modele.py"), str(PORTS["modele"])], env=env))
        journal = SAAS / "donnees-demo" / "moteur.log"
        journal.parent.mkdir(parents=True, exist_ok=True)
        sortie = open(journal, "w", encoding="utf-8", errors="replace")
        moteur_proc = subprocess.Popen([opencode, "serve", "--hostname", "127.0.0.1", "--port", str(PORTS["moteur"])],
                                       cwd=RACINE, env=env, stdout=sortie, stderr=subprocess.STDOUT)
        procs.append(moteur_proc)
        print(f"Démarrage du moteur OpenCode ({opencode}, port {PORTS['moteur']})...")
        url_moteur = f"http://127.0.0.1:{PORTS['moteur']}/session/status"
        fin = time.time() + 120
        pret = False
        while time.time() < fin and moteur_proc.poll() is None:
            if attendre(url_moteur, delai=2, auth="opencode:" + env["OPENCODE_SERVER_PASSWORD"]):
                pret = True
                break
        if not pret:
            sortie.flush()
            texte = journal.read_text(encoding="utf-8", errors="replace").strip()
            etat = f"arrêté (code {moteur_proc.returncode})" if moteur_proc.poll() is not None else "toujours sans réponse après 2 minutes"
            sys.exit(f"Le moteur OpenCode n'a pas démarré : {etat}.\n"
                     f"--- Messages d'OpenCode ({journal}) ---\n{texte[-3000:] or '(aucun message)'}\n---")
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(SAAS),
                                       "--host", "127.0.0.1", "--port", str(PORTS["web"])], cwd=RACINE, env=env))
        url = f"http://127.0.0.1:{PORTS['web']}"
        if not attendre(url + "/sante"):
            sys.exit("L'application n'a pas démarré.")
        print(f"\nQA Factory : {url}   (modèle : {modele})\nIdentifiant : demo   Mot de passe : Demo-2026-qa (à changer à la 1re connexion)\nCtrl+C pour arrêter.\n")
        if not os.environ.get("QAF_SANS_NAVIGATEUR"):
            webbrowser.open(url)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.send_signal(signal.SIGINT) if os.name != "nt" else p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Démonstration arrêtée.")


if __name__ == "__main__":
    main()
