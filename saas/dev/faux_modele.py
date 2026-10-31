# -*- coding: utf-8 -*-
"""Faux modèle d'IA (API compatible OpenAI) pour essayer QA Factory SaaS sans clé OpenRouter.

Il ne réfléchit pas : il joue un scénario fixe, mais c'est le VRAI OpenCode qui l'exécute
(sessions, commandes, outils, demandes de confirmation). Utilisé pour les tests et les
démonstrations ; jamais en production.

Scénario pour /analyser <projet> :
  1. demande l'outil bash : copie l'analyse de référence de projets/saucedemo dans
     projets/<projet>/02-a-valider (commande non autorisée d'office : OpenCode demande
     confirmation, ce qui exerce le circuit de confirmation de l'application web) ;
  2. demande l'outil bash : régénère les vues et lance le contrôle ;
  3. rend un compte rendu.
Pour toute autre demande : répond un texte court.

Lancement : python saas/dev/faux_modele.py [port]   (défaut 4010)
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _texte(contenu):
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return " ".join(p.get("text", "") for p in contenu if isinstance(p, dict))
    return ""


def decider(corps):
    """Renvoie ('texte', str) ou ('outil', nom, arguments) selon la conversation."""
    messages = corps.get("messages") or []
    outils = {t.get("function", {}).get("name") for t in corps.get("tools") or []}
    utilisateur = " ".join(_texte(m.get("content")) for m in messages if m.get("role") == "user")
    resultats = [m for m in messages if m.get("role") == "tool"]
    m = re.search(r"projet\s+«\s*([a-z0-9][a-z0-9-]*)", utilisateur)
    if "bash" not in outils or not m or "analyse" not in utilisateur.lower():
        return ("texte", "Réponse du faux modèle de démonstration.")
    projet = m.group(1)
    if not resultats:
        return ("outil", "bash", {
            "command": f"cp -r projets/saucedemo/02-a-valider/. projets/{projet}/02-a-valider/",
            "description": "Copie de l'analyse de référence (faux modèle)"})
    if len(resultats) == 1:
        return ("outil", "bash", {
            "command": f"python3 outils/rendre_revue.py {projet} --forcer && python3 outils/controle.py {projet}",
            "description": "Vues et contrôle"})
    return ("texte", f"Analyse terminée (faux modèle de démonstration) pour le projet {projet} : "
                     "17 exigences, 27 cas de tests, 11 questions dont 2 bloquantes (Q-002, Q-005). "
                     "Contrôle : 0 erreur. Relire cas-de-tests.xlsx ou cas-de-tests.docx, puis valider.")


class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json({"object": "list", "data": [{"id": "demo", "object": "model"}]})
        self._json({"ok": True})

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        decision = decider(corps)
        ident, cree = f"chatcmpl-{int(time.time() * 1000)}", int(time.time())
        if decision[0] == "texte":
            delta, fin = {"role": "assistant", "content": decision[1]}, "stop"
            message = {"role": "assistant", "content": decision[1]}
        else:
            appel = {"index": 0, "id": f"call_{int(time.time() * 1000)}", "type": "function",
                     "function": {"name": decision[1], "arguments": json.dumps(decision[2], ensure_ascii=False)}}
            delta, fin = {"role": "assistant", "content": None, "tool_calls": [appel]}, "tool_calls"
            message = {"role": "assistant", "content": None,
                       "tool_calls": [{k: v for k, v in appel.items() if k != "index"}]}
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        if not corps.get("stream"):
            return self._json({"id": ident, "object": "chat.completion", "created": cree, "model": "demo",
                               "choices": [{"index": 0, "message": message, "finish_reason": fin}], "usage": usage})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for morceau in ({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": fin}], "usage": usage}):
            morceau.update({"id": ident, "object": "chat.completion.chunk", "created": cree, "model": "demo"})
            self.wfile.write(f"data: {json.dumps(morceau, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4010
    print(f"Faux modèle sur http://127.0.0.1:{port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire).serve_forever()


if __name__ == "__main__":
    main()
