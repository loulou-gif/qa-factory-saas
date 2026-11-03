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
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SAAS = RACINE / "saas"
# Le moteur n'utilise pas 4096 : c'est le port par défaut d'OpenCode, souvent déjà pris par OpenCode lui-même.
PORTS = {"modele": int(os.environ.get("QAF_PORT_MODELE", "4110")), "moteur": int(os.environ.get("QAF_PORT_MOTEUR", "4196")),
         "web": int(os.environ.get("QAF_PORT", "8000"))}


def arreter(proc_ou_pid):
    """Arrête un processus et ses enfants. Sous Windows, opencode.CMD lance node : sans /T, node survit
    et garde le port occupé."""
    pid = proc_ou_pid if isinstance(proc_ou_pid, int) else proc_ou_pid.pid
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGINT)
        except OSError:
            pass


def libre(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# Requêtes locales sans proxy : sous Windows, urllib et httpx reprennent le proxy du système
# (souvent celui de l'entreprise), qui ne sait pas joindre 127.0.0.1.
_SANS_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sonder(url, auth=None):
    """None si le service répond ; sinon la raison, pour le diagnostic."""
    req = urllib.request.Request(url)
    if auth:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    try:
        _SANS_PROXY.open(req, timeout=5)
        return None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "mot de passe du moteur refusé (HTTP 401)"
        return None  # le serveur répond : il est démarré
    except Exception as e:  # noqa: BLE001
        return f"{e.__class__.__name__} : {e}"


def attendre(url, delai=90, auth=None):
    fin = time.time() + delai
    while time.time() < fin:
        if sonder(url, auth) is None:
            return True
        time.sleep(0.5)
    return False


def _arret_demande(*_):
    raise KeyboardInterrupt  # fermeture de la fenêtre ou arrêt du service : même nettoyage que Ctrl+C


def main():
    signal.signal(signal.SIGTERM, _arret_demande)
    if hasattr(signal, "SIGBREAK"):  # Windows : fermeture de la console
        signal.signal(signal.SIGBREAK, _arret_demande)
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
    fichier_pid = SAAS / "donnees-demo" / "demo.pid"
    if fichier_pid.exists():  # processus restés actifs après une démo précédente (fenêtre fermée…) : on les arrête
        for ligne in fichier_pid.read_text().split():
            if ligne.isdigit():
                arreter(int(ligne))
        time.sleep(1)
        fichier_pid.unlink(missing_ok=True)
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
    locaux = "127.0.0.1,localhost"
    for cle in ("NO_PROXY", "no_proxy"):
        env[cle] = ",".join(x for x in (env.get(cle, ""), locaux) if x)
    env.setdefault("SQUASH_MCP_DIR", str(RACINE.parent / "squash-tm-mcp"))
    env.setdefault("SQUASH_TM_BASE_URL", "")
    procs = []
    try:
        if modele == "simulation/demo":
            procs.append(subprocess.Popen([sys.executable, str(SAAS / "dev" / "faux_modele.py"), str(PORTS["modele"])], env=env))
        journal = SAAS / "donnees-demo" / "moteur.log"
        journal.parent.mkdir(parents=True, exist_ok=True)
        sortie = open(journal, "w", encoding="utf-8", errors="replace")
        # OpenCode insère les variables {env:…} telles quelles dans opencode.json avant de le lire :
        # un chemin Windows (C:\Users\…) ou un mot de passe avec " ou \ rend le fichier illisible.
        # L'agent n'a de toute façon pas accès à Squash : on retire ces variables de son environnement.
        env_moteur = {k: v for k, v in env.items() if not k.upper().startswith(("SQUASH_TM_", "SQUASH_MCP_"))}
        moteur_proc = subprocess.Popen([opencode, "serve", "--hostname", "127.0.0.1", "--port", str(PORTS["moteur"])],
                                       cwd=RACINE, env=env_moteur, stdout=sortie, stderr=subprocess.STDOUT)
        procs.append(moteur_proc)
        fichier_pid.write_text("\n".join(str(x.pid) for x in procs))
        print(f"Démarrage du moteur OpenCode ({opencode}, port {PORTS['moteur']})...")
        url_moteur = f"http://127.0.0.1:{PORTS['moteur']}/session/status"
        fin = time.time() + 120
        pret, raison = False, "pas encore de réponse"
        while time.time() < fin and moteur_proc.poll() is None:
            raison = sonder(url_moteur, auth="opencode:" + env["OPENCODE_SERVER_PASSWORD"])
            if raison is None:
                pret = True
                break
            time.sleep(1)
        if not pret:
            sortie.flush()
            texte = journal.read_text(encoding="utf-8", errors="replace").strip()
            etat = (f"arrêté (code {moteur_proc.returncode})" if moteur_proc.poll() is not None
                    else f"toujours sans réponse après 2 minutes ; dernière erreur de connexion : {raison}")
            sys.exit(f"Le moteur OpenCode n'a pas démarré : {etat}.\n"
                     f"--- Messages d'OpenCode ({journal}) ---\n{texte[-3000:] or '(aucun message)'}\n---")
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(SAAS),
                                       "--host", "127.0.0.1", "--port", str(PORTS["web"])], cwd=RACINE, env=env))
        fichier_pid.write_text("\n".join(str(x.pid) for x in procs))
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
            if p.poll() is None or os.name == "nt":
                arreter(p)
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        fichier_pid.unlink(missing_ok=True)
        print("Démonstration arrêtée.")


if __name__ == "__main__":
    main()
