# -*- coding: utf-8 -*-
"""Faux Squash TM en mémoire (API REST minimale) pour tester la publication sans instance réelle.

Reprend le comportement du faux serveur des tests du MCP squash-tm (test/fakeSquash.ts),
avec l'authentification par identifiant et mot de passe et un projet n° 28.
"""
import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IDENTIFIANTS = ("qa", "secret")


class FauxSquash:
    def __init__(self):
        self.prochain = 1000
        self.store = {"projects": {28: {"_type": "project", "id": 28, "name": "SauceDemo"}},
                      "requirements": {}, "testCases": {}, "reqFolders": {}, "tcFolders": {}, "coverages": [],
                      "datasets": {}, "parameters": {}}
        self.store["projects"][29] = {"_type": "project", "id": 29, "name": "Autre projet"}
        self.requetes = []
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
                if self.headers.get("Authorization") != attendu:
                    return self._envoyer(401, {"error": "unauthorized"})
                n = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(n) or b"null") if n else None
                chemin, _, requete = self.path.partition("?")
                p = re.sub(r"^/api/rest/latest", "", chemin)
                with faux.verrou:
                    faux.requetes.append((self.command, p, corps))
                    return faux.repondre(self, self.command, p, requete, corps)

            do_GET = do_POST = do_PATCH = _traiter

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), G)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}/api/rest/latest"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def _id(self):
        self.prochain += 1
        return self.prochain

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
        if methode == "POST" and p == "/requirements":
            i = self._id()
            s["requirements"][i] = {"_type": "requirement", "id": i, "name": corps["current_version"]["name"],
                                    "current_version": corps["current_version"], "parent": corps.get("parent")}
            return h._envoyer(201, s["requirements"][i])
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
            s["testCases"][i]["id"] = i
            jeux = []
            for d in corps.get("datasets") or []:
                j = self._id()
                s["datasets"][j] = {"_type": "dataset", "id": j, "name": d["name"], "test_case": i, "parameter_values": []}
                jeux.append({"_type": "dataset", "id": j, "name": d["name"]})
            s["testCases"][i]["datasets"] = jeux
            s["testCases"][i]["parameters"] = []
            return h._envoyer(201, s["testCases"][i])
        m = re.match(r"^/test-cases/(\d+)/coverages/([\d,]+)$", p)
        if methode == "POST" and m:
            s["coverages"].append((int(m.group(1)), m.group(2)))
            return h._envoyer(200, s["testCases"].get(int(m.group(1)), {}))
        if methode == "POST" and re.match(r"^/test-cases/\d+/steps$", p):
            return h._envoyer(201, {"_type": "action-step", "id": self._id(), **(corps or {})})
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
