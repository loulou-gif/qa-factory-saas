# -*- coding: utf-8 -*-
"""Base de données SQLite : utilisateurs, connexions Squash et comptes de test de l'application (chiffrés), projets, tâches, journal d'audit.

Le contenu des projets (documents, analyses, livrables) reste dans les dossiers projets/<code>/,
exactement comme dans qa-factory : les skills et les scripts fonctionnent sans changement.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS utilisateurs (
  id INTEGER PRIMARY KEY,
  identifiant TEXT UNIQUE NOT NULL,
  nom TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'responsable', 'testeur')),
  mot_de_passe TEXT NOT NULL,
  actif INTEGER NOT NULL DEFAULT 1,
  doit_changer INTEGER NOT NULL DEFAULT 1,
  cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projets (
  code TEXT PRIMARY KEY,
  responsable_id INTEGER REFERENCES utilisateurs(id),
  cree_par INTEGER REFERENCES utilisateurs(id),
  cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS taches (
  id INTEGER PRIMARY KEY,
  projet TEXT NOT NULL,
  type TEXT NOT NULL,
  statut TEXT NOT NULL,
  parametres TEXT NOT NULL DEFAULT '{}',
  session_id TEXT,
  attente TEXT,
  journal TEXT NOT NULL DEFAULT '[]',
  resultat TEXT,
  annulation INTEGER NOT NULL DEFAULT 0,
  cree_par INTEGER REFERENCES utilisateurs(id),
  cree_le TEXT NOT NULL,
  debut TEXT,
  fin TEXT
);
CREATE INDEX IF NOT EXISTS taches_projet ON taches(projet, id);
CREATE TABLE IF NOT EXISTS connexions_squash (
  utilisateur_id INTEGER PRIMARY KEY REFERENCES utilisateurs(id),
  url TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('compte', 'jeton')),
  identifiant TEXT,
  secret TEXT NOT NULL,
  verifiee_le TEXT,
  projets_visibles INTEGER,
  maj_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comptes_test (
  id INTEGER PRIMARY KEY,
  projet TEXT NOT NULL,
  libelle TEXT NOT NULL,
  identifiant TEXT NOT NULL,
  secret TEXT NOT NULL,
  cree_par INTEGER REFERENCES utilisateurs(id),
  maj_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comptes_test_projet ON comptes_test(projet, id);
CREATE TABLE IF NOT EXISTS reglages_app (
  cle TEXT PRIMARY KEY,
  valeur TEXT NOT NULL,
  maj_par INTEGER REFERENCES utilisateurs(id),
  maj_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  quand TEXT NOT NULL,
  utilisateur_id INTEGER,
  projet TEXT,
  action TEXT NOT NULL,
  detail TEXT
);
"""

STATUTS_ACTIFS = ("en_attente", "en_cours", "attente_confirmation")


def maintenant():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Base:
    def __init__(self, chemin):
        self.chemin = str(chemin)
        self._verrou = threading.RLock()
        self._cx = sqlite3.connect(self.chemin, check_same_thread=False, isolation_level=None)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute("PRAGMA foreign_keys=ON")
        self._cx.executescript(SCHEMA)

    def x(self, sql, params=()):
        with self._verrou:
            return self._cx.execute(sql, params)

    def un(self, sql, params=()):
        with self._verrou:
            r = self._cx.execute(sql, params).fetchone()
            return dict(r) if r else None

    def tous(self, sql, params=()):
        with self._verrou:
            return [dict(r) for r in self._cx.execute(sql, params).fetchall()]

    # -- audit
    def auditer(self, utilisateur_id, projet, action, detail=""):
        self.x("INSERT INTO audit (quand, utilisateur_id, projet, action, detail) VALUES (?,?,?,?,?)",
               (maintenant(), utilisateur_id, projet, action, detail))

    # -- tâches
    def tache(self, tid):
        t = self.un("SELECT t.*, u.nom AS auteur FROM taches t LEFT JOIN utilisateurs u ON u.id = t.cree_par WHERE t.id = ?", (tid,))
        if t:
            for k, defaut in (("parametres", {}), ("journal", []), ("attente", None), ("resultat", None)):
                t[k] = json.loads(t[k]) if t[k] else defaut
        return t

    def ajouter_journal(self, tid, ligne):
        with self._verrou:
            j = json.loads(self.un("SELECT journal FROM taches WHERE id = ?", (tid,))["journal"])
            j.append({"t": maintenant()[11:19], "m": ligne})
            self.x("UPDATE taches SET journal = ? WHERE id = ?", (json.dumps(j[-500:], ensure_ascii=False), tid))

    def maj_tache(self, tid, **champs):
        for k in ("parametres", "attente", "resultat"):
            if k in champs and champs[k] is not None and not isinstance(champs[k], str):
                champs[k] = json.dumps(champs[k], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in champs)
        self.x(f"UPDATE taches SET {cols} WHERE id = ?", (*champs.values(), tid))
