# -*- coding: utf-8 -*-
"""Réglages de l'application, lus dans les variables d'environnement (voir saas/.env.exemple)."""
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

ICI = Path(__file__).resolve().parent


def _bool(nom, defaut=False):
    v = os.environ.get(nom)
    return defaut if v is None else v.strip().lower() in ("1", "true", "oui", "yes")


@dataclass
class Reglages:
    racine: Path = field(default_factory=lambda: Path(os.environ.get("QAF_RACINE") or ICI.parents[1]).resolve())
    donnees: Path = field(default_factory=lambda: Path(os.environ.get("QAF_DONNEES") or (ICI.parent / "donnees")).resolve())
    secret: str = field(default_factory=lambda: os.environ.get("QAF_SECRET") or "")
    opencode_url: str = field(default_factory=lambda: os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096"))
    opencode_utilisateur: str = field(default_factory=lambda: os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"))
    opencode_mot_de_passe: str = field(default_factory=lambda: os.environ.get("OPENCODE_SERVER_PASSWORD", ""))
    modele: str = field(default_factory=lambda: os.environ.get("QAF_MODELE", ""))
    squash_mcp_dir: str = field(default_factory=lambda: os.environ.get("SQUASH_MCP_DIR", ""))
    squash_url: str = field(default_factory=lambda: os.environ.get("SQUASH_TM_BASE_URL", ""))
    taches_paralleles: int = field(default_factory=lambda: int(os.environ.get("QAF_TACHES_PARALLELES", "2")))
    duree_max_tache_min: int = field(default_factory=lambda: int(os.environ.get("QAF_DUREE_MAX_TACHE_MIN", "90")))
    taille_max_mo: int = field(default_factory=lambda: int(os.environ.get("QAF_TAILLE_MAX_MO", "50")))
    cookie_securise: bool = field(default_factory=lambda: _bool("QAF_COOKIE_SECURISE", False))
    intervalle_suivi_s: float = field(default_factory=lambda: float(os.environ.get("QAF_INTERVALLE_SUIVI_S", "2")))

    @property
    def projets(self) -> Path:
        return self.racine / "projets"

    @property
    def outils(self) -> Path:
        return self.racine / "outils"

    @property
    def base(self) -> Path:
        return self.donnees / "qa-factory.sqlite3"

    def preparer(self):
        self.donnees.mkdir(parents=True, exist_ok=True)
        self.projets.mkdir(parents=True, exist_ok=True)
        if not self.secret:
            f = self.donnees / ".secret"
            if not f.exists():
                f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            self.secret = f.read_text(encoding="utf-8").strip()
        if str(self.outils) not in sys.path:
            sys.path.insert(0, str(self.outils))
        return self


reglages = Reglages()
