#!/usr/bin/env node
// Publication Squash TM sans IA, pour l'application web QA Factory SaaS.
//
// Utilise le code de publication du MCP squash-tm (fork) : mêmes règles, même fichier de
// correspondance, mêmes garanties (rien n'est modifié ni supprimé dans Squash, reprise sans
// doublon). L'application lance d'abord une simulation, la montre au responsable du projet,
// puis relance avec --appliquer après son clic de confirmation.
//
// Usage :
//   node saas/publier_squash.mjs --fichier <cas-de-tests.json> --correspondance <correspondance.json> [--appliquer]
// Variables : SQUASH_MCP_DIR (dossier du MCP squash-tm, compilé), SQUASH_TM_BASE_URL,
//             SQUASH_TM_API_TOKEN ou SQUASH_TM_USERNAME + SQUASH_TM_PASSWORD.
// Sortie : le résultat en JSON sur la sortie standard. Code 0 si terminé sans erreur, 1 sinon.

import path from 'node:path';

const args = process.argv.slice(2);
const valeur = (nom) => {
  const i = args.indexOf(nom);
  return i >= 0 ? args[i + 1] : undefined;
};
const fichier = valeur('--fichier');
const correspondance = valeur('--correspondance');
const appliquer = args.includes('--appliquer');
const dossierMcp = process.env.SQUASH_MCP_DIR || '';

const sortir = (obj, code) => {
  process.stdout.write(JSON.stringify(obj, null, 1) + '\n');
  process.exit(code);
};

if (!fichier || !correspondance) sortir({ termine: false, erreurs: ['--fichier et --correspondance sont obligatoires'] }, 1);
if (!dossierMcp) sortir({ termine: false, erreurs: ['SQUASH_MCP_DIR non défini'] }, 1);
if (!process.env.SQUASH_TM_BASE_URL) sortir({ termine: false, erreurs: ['SQUASH_TM_BASE_URL non défini'] }, 1);

let SquashTMClient, publierFichier;
try {
  ({ SquashTMClient } = await import(path.join(dossierMcp, 'dist/clients/index.js')));
  ({ publierFichier } = await import(path.join(dossierMcp, 'dist/publish/publishBatch.js')));
} catch (e) {
  sortir({ termine: false, erreurs: [`MCP squash-tm introuvable ou non compilé dans ${dossierMcp} : ${e.message}`] }, 1);
}

try {
  const client = new SquashTMClient();
  const resultat = await publierFichier(client, {
    fichier: path.resolve(fichier),
    fichierCorrespondance: path.resolve(correspondance),
    appliquer,
    squashUrl: process.env.SQUASH_TM_BASE_URL,
  });
  sortir(resultat, resultat.erreurs && resultat.erreurs.length ? 1 : 0);
} catch (e) {
  sortir({ termine: false, erreurs: [String(e && e.message ? e.message : e)] }, 1);
}
