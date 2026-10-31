# -*- coding: utf-8 -*-
"""Administration en ligne de commande (sur le serveur).

  python -m app.admin creer-admin <identifiant> "<Nom complet>"   # demande le mot de passe
  python -m app.admin lister
"""
import getpass
import sys

from .config import reglages
from .db import Base, maintenant
from .securite import hacher, mot_de_passe_valable


def main(argv):
    reglages.preparer()
    base = Base(reglages.base)
    if len(argv) >= 3 and argv[0] == "creer-admin":
        ident, nom = argv[1].strip().lower(), argv[2].strip()
        mdp = getpass.getpass("Mot de passe provisoire : ")
        if mot_de_passe_valable(mdp):
            sys.exit(f"Mot de passe trop faible : {mot_de_passe_valable(mdp)}")
        if base.un("SELECT id FROM utilisateurs WHERE identifiant = ?", (ident,)):
            base.x("UPDATE utilisateurs SET role = 'admin', actif = 1, mot_de_passe = ?, doit_changer = 1 WHERE identifiant = ?",
                   (hacher(mdp), ident))
            print(f"Compte {ident} : administrateur, mot de passe réinitialisé.")
        else:
            base.x("INSERT INTO utilisateurs (identifiant, nom, role, mot_de_passe, doit_changer, cree_le) VALUES (?,?,?,?,1,?)",
                   (ident, nom, "admin", hacher(mdp), maintenant()))
            print(f"Administrateur {ident} créé (mot de passe à changer à la première connexion).")
    elif argv[:1] == ["lister"]:
        for u in base.tous("SELECT identifiant, nom, role, actif FROM utilisateurs ORDER BY nom"):
            print(f"{u['identifiant']:<25} {u['nom']:<30} {u['role']:<12} {'actif' if u['actif'] else 'désactivé'}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
