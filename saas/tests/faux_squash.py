# -*- coding: utf-8 -*-
"""Faux Squash TM en mémoire (API REST minimale) pour tester la publication sans instance réelle.

Reprend le comportement du faux serveur des tests du MCP squash-tm (test/fakeSquash.ts),
avec l'authentification par identifiant et mot de passe et un projet n° 28.
"""
import base64
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IDENTIFIANTS = ("qa", "secret")
JETON = "jeton-valide"
JETON_SANS_JWT = "instance-sans-jwt"  # simule une instance où les jetons d'API ne sont pas activés


class FauxSquash:
    def __init__(self):
        self.prochain = 1000
        self.store = {"projects": {28: {"_type": "project", "id": 28, "name": "SauceDemo"}},
                      "requirements": {}, "testCases": {}, "reqFolders": {}, "tcFolders": {}, "coverages": [],
                      "datasets": {}, "parameters": {}}
        self.store["projects"][29] = {"_type": "project", "id": 29, "name": "Autre projet"}
        self.requetes = []
        self.authentifications = []
        self.lenteur_creation = 0.0  # secondes ajoutées à chaque POST (essais d'arrêt en cours d'envoi)
        self.verrou = threading.Lock()
        faux = self

        class G(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _envoyer(self, code, obj=None):
                b = b"" if obj is None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _traiter(self):
                attendu = "Basic " + base64.b64encode(":".join(IDENTIFIANTS).encode()).decode()
                recu = self.headers.get("Authorization")
                faux.authentifications.append(recu)
                if recu == f"Bearer {JETON_SANS_JWT}":
                    return self._envoyer(401, {"error": "Aucun secret JWT n'est défini pour cette instance."})
                if recu not in (attendu, f"Bearer {JETON}"):
                    return self._envoyer(401, {"error": "unauthorized"})
                if self.command == "POST" and faux.lenteur_creation:
                    time.sleep(faux.lenteur_creation)
                n = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(n) or b"null") if n else None
                chemin, _, requete = self.path.partition("?")
                p = re.sub(r"^/api/rest/latest", "", chemin)
                with faux.verrou:
                    faux.requetes.append((self.command, p, corps))
                    return faux.repondre(self, self.command, p, requete, corps)

            do_GET = do_POST = do_PATCH = do_DELETE = _traiter

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), G)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}/api/rest/latest"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def _id(self):
        self.prochain += 1
        return self.prochain

    @staticmethod
    def html(v):
        """Squash reformate le HTML (retour à la ligne après chaque paragraphe)."""
        return re.sub(r"</p>(?!\n)", "</p>\n", v) if isinstance(v, str) else v

    def projet_de(self, parent):
        """Projet d'un élément, en remontant ses dossiers parents."""
        for _ in range(50):
            if not parent:
                return None
            if parent.get("_type") == "project":
                return parent.get("id")
            dossiers = self.store["reqFolders"] if parent.get("_type") == "requirement-folder" else self.store["tcFolders"]
            parent = (dossiers.get(parent.get("id")) or {}).get("parent")
        return None

    def chemin(self, parent, nom):
        """Chemin tel que Squash le donne : /<projet>/<dossiers>/<nom>."""
        morceaux = [nom or ""]
        for _ in range(50):
            if not parent:
                break
            if parent.get("_type") == "project":
                morceaux.insert(0, (self.store["projects"].get(parent.get("id")) or {}).get("name", f"P{parent.get('id')}"))
                break
            dossiers = self.store["reqFolders"] if parent.get("_type") == "requirement-folder" else self.store["tcFolders"]
            d = dossiers.get(parent.get("id"))
            if not d:
                break
            morceaux.insert(0, d["name"])
            parent = d.get("parent")
        return "/" + "/".join(morceaux)

    def _cas_du_pas(self, sid):
        return next((t for t in self.store["testCases"].values() if any(x.get("id") == sid for x in t.get("steps") or [])), None)

    def repondre(self, h, methode, p, requete, corps):
        s = self.store
        m = re.match(r"^/projects/(\d+)$", p)
        if methode == "GET" and m:
            pr = s["projects"].get(int(m.group(1)))
            return h._envoyer(200, pr) if pr else h._envoyer(404)
        if methode == "GET" and p == "/projects" and "projectName=" not in requete:
            liste = sorted(s["projects"].values(), key=lambda x: x["id"])
            return h._envoyer(200, {"_embedded": {"projects": liste}, "page": {"size": 200, "totalElements": len(liste), "totalPages": 1, "number": 0}})
        if methode == "GET" and p == "/projects" and "projectName=" in requete:
            nom = requete.split("projectName=")[1].split("&")[0]
            pr = next((x for x in s["projects"].values() if x["name"] == nom), None)
            return h._envoyer(200, pr) if pr else h._envoyer(404)
        # Comme Squash 9 : deux éléments de même nom dans le même conteneur sont refusés
        def meme_conteneur(elements, parent, nom):
            return any(x.get("name") == nom and (x.get("parent") or {}).get("_type") == (parent or {}).get("_type")
                       and (x.get("parent") or {}).get("id") == (parent or {}).get("id") for x in elements.values())
        if methode == "POST" and p in ("/requirements", "/test-cases"):
            nom = (corps.get("current_version") or {}).get("name") if p == "/requirements" else corps.get("name")
            if meme_conteneur(s["requirements" if p == "/requirements" else "testCases"], corps.get("parent"), nom):
                return h._envoyer(412, {"status": 412, "message": f"Cannot rename {nom} : {nom} already exists within the same container"})
        if methode == "POST" and p == "/requirements":
            i = self._id()
            v = dict(corps["current_version"], description=self.html(corps["current_version"].get("description")))
            s["requirements"][i] = {"_type": "requirement", "id": i, "name": v["name"], "current_version": v, "parent": corps.get("parent")}
            return h._envoyer(201, s["requirements"][i])
        m = re.match(r"^/requirements/(\d+)$", p)
        if methode == "PATCH" and m:
            r = s["requirements"].get(int(m.group(1)))
            if not r:
                return h._envoyer(404)
            champs = {k: v for k, v in corps["current_version"].items() if k != "_type"}
            # Comme Squash 9 : une version obsolète ne change plus ; une version approuvée, seulement son statut.
            if r["current_version"].get("status") == "OBSOLETE":
                return h._envoyer(412, {"error": "Can not change an obsolete requirement"})
            if r["current_version"].get("status") == "APPROVED" and set(champs) - {"status"}:
                return h._envoyer(412, {"error": "La version approuvée est verrouillée."})
            if "description" in champs:
                champs["description"] = self.html(champs["description"])
            r["current_version"].update(champs)
            r["name"] = r["current_version"]["name"]
            return h._envoyer(200, r)
        m = re.match(r"^/projects/(\d+)/(test-cases|requirements)$", p)
        if methode == "GET" and m:
            pid = int(m.group(1))
            if m.group(2) == "test-cases":
                liste = [{"_type": "test-case", "id": t["id"], "name": t.get("name"), "reference": t.get("reference", ""),
                          "path": self.chemin(t.get("parent"), t.get("name"))}
                         for t in s["testCases"].values() if self.projet_de(t.get("parent")) == pid]
                return h._envoyer(200, {"_embedded": {"test-cases": liste}, "page": {"size": 200, "totalElements": len(liste), "totalPages": 1, "number": 0}})
            liste = [{"_type": "requirement", "id": r["id"], "name": r.get("name"), "path": self.chemin(r.get("parent"), r.get("name"))}
                     for r in s["requirements"].values() if self.projet_de(r.get("parent")) == pid]
            return h._envoyer(200, {"_embedded": {"requirements": liste}, "page": {"size": 200, "totalElements": len(liste), "totalPages": 1, "number": 0}})
        for cle, motif, typ in (("requirements", r"^/requirements/(\d+)$", None), ("reqFolders", r"^/requirement-folders/(\d+)$", None),
                                ("tcFolders", r"^/test-case-folders/(\d+)$", None), ("testCases", r"^/test-cases/(\d+)$", None)):
            m = re.match(motif, p)
            if methode == "GET" and m:
                x = s[cle].get(int(m.group(1)))
                return h._envoyer(200, x) if x else h._envoyer(404)
        if methode == "POST" and p in ("/requirement-folders", "/test-case-folders"):
            i = self._id()
            cle = "reqFolders" if p == "/requirement-folders" else "tcFolders"
            s[cle][i] = {"_type": p.strip("/").rstrip("s"), "id": i, "name": corps["name"], "parent": corps.get("parent")}
            return h._envoyer(201, s[cle][i])
        if methode == "POST" and p == "/test-cases":
            if corps.get("_type") != "test-case":
                return h._envoyer(400, {"error": "expected standard test case"})
            i = self._id()
            s["testCases"][i] = {"_type": "test-case", "id": i, "name": corps.get("name"), **corps}
            s["testCases"][i].update(id=i, description=self.html(corps.get("description")), prerequisite=self.html(corps.get("prerequisite")),
                                     steps=[dict(x, id=self._id(), action=self.html(x["action"]), expected_result=self.html(x["expected_result"]))
                                            for x in corps.get("steps") or []],
                                     verified_requirements=[{"_type": "requirement-version", "id": r["id"]} for r in corps.get("verified_requirements") or []])
            jeux = []
            for d in corps.get("datasets") or []:
                j = self._id()
                s["datasets"][j] = {"_type": "dataset", "id": j, "name": d["name"], "test_case": i, "parameter_values": []}
                jeux.append({"_type": "dataset", "id": j, "name": d["name"]})
            s["testCases"][i]["datasets"] = jeux
            s["testCases"][i]["parameters"] = []
            return h._envoyer(201, s["testCases"][i])
        m = re.match(r"^/test-cases/(\d+)$", p)
        if methode == "PATCH" and m:
            t = s["testCases"].get(int(m.group(1)))
            if not t:
                return h._envoyer(404)
            champs = {k: v for k, v in corps.items() if k != "_type"}
            for k in ("description", "prerequisite"):
                if k in champs:
                    champs[k] = self.html(champs[k])
            t.update(champs)
            return h._envoyer(200, t)
        m = re.match(r"^/test-cases/(\d+)/coverages/([\d,]+)$", p)
        if methode in ("POST", "DELETE") and m:
            t = s["testCases"].get(int(m.group(1)), {})
            ids = [int(x) for x in m.group(2).split(",")]
            if methode == "POST":
                s["coverages"].append((int(m.group(1)), m.group(2)))
                deja = {r["id"] for r in t.get("verified_requirements") or []}
                t.setdefault("verified_requirements", []).extend({"_type": "requirement-version", "id": x} for x in ids if x not in deja)
                return h._envoyer(200, t)
            t["verified_requirements"] = [r for r in t.get("verified_requirements") or [] if r["id"] not in ids]
            return h._envoyer(204)
        m = re.match(r"^/test-cases/(\d+)/steps$", p)
        if methode == "POST" and m:
            st = {"_type": "action-step", "id": self._id(), "action": self.html(corps.get("action")), "expected_result": self.html(corps.get("expected_result"))}
            s["testCases"].get(int(m.group(1)), {}).setdefault("steps", []).append(st)
            return h._envoyer(201, st)
        m = re.match(r"^/test-steps/(\d+)$", p)
        if methode == "PATCH" and m:
            t = self._cas_du_pas(int(m.group(1)))
            if not t:
                return h._envoyer(404)
            st = next(x for x in t["steps"] if x["id"] == int(m.group(1)))
            st.update(action=self.html(corps["action"]), expected_result=self.html(corps["expected_result"]))
            return h._envoyer(200, st)
        m = re.match(r"^/test-steps/([\d,]+)$", p)
        if methode == "DELETE" and m:
            ids = [int(x) for x in m.group(1).split(",")]
            for t in s["testCases"].values():
                t["steps"] = [x for x in t.get("steps") or [] if x["id"] not in ids]
            return h._envoyer(204)
        if methode == "POST" and re.match(r"^/test-steps/\d+/coverages/[\d,]+$", p):
            return h._envoyer(200, {})
        if methode == "POST" and p == "/parameters":
            i = self._id()
            tc = s["testCases"][corps["test_case"]["id"]]
            prm = {"_type": "parameter", "id": i, "name": corps["name"]}
            s["parameters"][i] = prm
            tc["parameters"].append(prm)
            return h._envoyer(201, prm)
        if methode == "POST" and p == "/datasets":
            i = self._id()
            tcid = corps["test_case"]["id"]
            s["datasets"][i] = {"_type": "dataset", "id": i, "name": corps["name"], "test_case": tcid,
                                "parameter_values": corps.get("parameter_values") or []}
            s["testCases"][tcid]["datasets"].append({"_type": "dataset", "id": i, "name": corps["name"]})
            return h._envoyer(201, s["datasets"][i])
        m = re.match(r"^/datasets/(\d+)$", p)
        if m and int(m.group(1)) in s["datasets"]:
            ds = s["datasets"][int(m.group(1))]
            if methode == "GET":
                return h._envoyer(200, ds)
            if methode == "PATCH":
                if len(corps.get("parameter_values") or []) > 7:
                    return h._envoyer(400, {"error": "max 7"})
                for v in corps.get("parameter_values") or []:
                    ds["parameter_values"] = [x for x in ds["parameter_values"] if x["parameter_id"] != v["parameter_id"]] + [v]
                return h._envoyer(200, ds)
        return h._envoyer(404, {"error": f"non géré : {methode} {p}"})

    def arreter(self):
        self.serveur.shutdown()
