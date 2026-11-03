#!/usr/bin/env node
// Publication Squash TM sans IA, pour l'application web QA Factory SaaS.
//
// Utilise le code de publication du MCP squash-tm (fork) : mêmes règles, même fichier de
// correspondance, mêmes garanties (rien n'est modifié ni supprimé dans Squash, reprise sans
// doublon). L'application lance d'abord une simulation, la montre au responsable du projet,
// puis relance avec --appliquer après son clic de confirmation.
//
// Usage :
//   node saas/publier_squash.mjs --fichier <publication.json> --correspondance <correspondance.json> [--jeux <jeux-squash.json>] [--appliquer]
//   node saas/publier_squash.mjs --lister-projets
//
// Jeux de données (--jeux) : sur les cas créés par QA Factory (présents dans la correspondance), crée les
// paramètres et les jeux manquants et renseigne un jeu dont toutes les valeurs sont vides. Un jeu qui a déjà
// au moins une valeur dans Squash n'est jamais modifié.
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

const lister = args.includes('--lister-projets');
const fichierJeux = valeur('--jeux');
if (!lister && (!fichier || !correspondance)) sortir({ termine: false, erreurs: ['--fichier et --correspondance sont obligatoires'] }, 1);
if (!dossierMcp) sortir({ termine: false, erreurs: ['SQUASH_MCP_DIR non défini'] }, 1);
if (!process.env.SQUASH_TM_BASE_URL) sortir({ termine: false, erreurs: ['SQUASH_TM_BASE_URL non défini'] }, 1);

let SquashTMClient, publierFichier;
try {
  ({ SquashTMClient } = await import(path.join(dossierMcp, 'dist/clients/index.js')));
  ({ publierFichier } = await import(path.join(dossierMcp, 'dist/publish/publishBatch.js')));
} catch (e) {
  sortir({ termine: false, erreurs: [`MCP squash-tm introuvable ou non compilé dans ${dossierMcp} : ${e.message}`] }, 1);
}

const client = new SquashTMClient();

if (lister) {
  try {
    const projets = [];
    for (let page = 0; page < 50; page++) {
      const r = await client.getAllProjects({ page, size: 200, type: 'STANDARD' });
      for (const p of (r._embedded && r._embedded.projects) || []) projets.push({ id: p.id, nom: p.name });
      const total = (r.page && r.page.totalPages) || 1;
      if (page + 1 >= total) break;
    }
    projets.sort((a, b) => a.nom.localeCompare(b.nom, 'fr'));
    sortir({ termine: true, projets, erreurs: [] }, 0);
  } catch (e) {
    sortir({ termine: false, projets: [], erreurs: [String(e && e.message ? e.message : e)] }, 1);
  }
}

// ---- Jeux de données
async function traiterJeux(appliquer) {
  const fs = await import('node:fs');
  const bilan = { a_creer: 0, a_completer: 0, deja_renseignes: 0, crees: 0, completes: 0, erreurs: [] };
  if (!fichierJeux || !fs.existsSync(fichierJeux)) return bilan;
  const jeux = JSON.parse(fs.readFileSync(fichierJeux, 'utf8'));
  let corr = {};
  try { corr = JSON.parse(fs.readFileSync(correspondance, 'utf8')); } catch { /* rien de publié */ }
  const ids = corr.cas_de_tests || {};
  const parCas = {};
  for (const j of jeux) (parCas[j.cas] = parCas[j.cas] || []).push(j);
  const requete = (chemin, options) => client.parameterClient.makeRequest(`${client.parameterClient.baseURL}${chemin}`, options);
  for (const [cas, liste] of Object.entries(parCas)) {
    const id = ids[cas];
    if (!id) { bilan.a_creer += liste.length; continue; } // le cas sera créé avec ses jeux (simulation)
    try {
      let tc = await client.getTestCase(id);
      for (const j of liste) {
        const existant = (tc.datasets || []).find((d) => d.name === j.nom);
        let vide = true;
        if (existant) {
          const r = await requete(`/datasets/${existant.id}`);
          const ds = r.ok ? await r.json() : {};
          vide = !(ds.parameter_values || []).some((v) => String(v.parameter_value || '').trim() !== '');
          if (!vide) { bilan.deja_renseignes++; continue; }
          bilan.a_completer++;
        } else {
          bilan.a_creer++;
        }
        if (!appliquer) continue;
        for (const p of j.parametres) {
          if (!(tc.parameters || []).some((x) => x.name === p.nom)) await client.createParameter(id, p.nom);
        }
        tc = await client.getTestCase(id);
        const valeurs = j.parametres.map((p) => {
          const param = (tc.parameters || []).find((x) => x.name === p.nom);
          return { _type: 'parameter-value', parameter_test_case_id: id, parameter_id: param.id, parameter_name: p.nom, parameter_value: p.valeur || '' };
        });
        if (existant) {
          for (let i = 0; i < valeurs.length; i += 7) {
            const r = await requete(`/datasets/${existant.id}`, { method: 'PATCH', body: JSON.stringify({ _type: 'dataset', parameter_values: valeurs.slice(i, i + 7) }) });
            if (!r.ok) throw new Error(`jeu « ${j.nom} » : ${r.status} ${await r.text()}`);
          }
          bilan.completes++;
        } else {
          const r = await requete('/datasets', { method: 'POST', body: JSON.stringify({ _type: 'dataset', name: j.nom, test_case: { _type: 'test-case', id }, parameter_values: valeurs }) });
          if (!r.ok) throw new Error(`jeu « ${j.nom} » : ${r.status} ${await r.text()}`);
          bilan.crees++;
        }
      }
    } catch (e) {
      bilan.erreurs.push(`${cas} : ${String(e && e.message ? e.message : e)}`);
    }
  }
  return bilan;
}

try {
  const resultat = await publierFichier(client, {
    fichier: path.resolve(fichier),
    fichierCorrespondance: path.resolve(correspondance),
    appliquer,
    squashUrl: process.env.SQUASH_TM_BASE_URL,
  });
  if (!resultat.erreurs || !resultat.erreurs.length) {
    resultat.jeux = await traiterJeux(appliquer);
    if (resultat.jeux.erreurs.length) resultat.erreurs = resultat.jeux.erreurs.map((e) => `Jeu de données, ${e}`);
  }
  sortir(resultat, resultat.erreurs && resultat.erreurs.length ? 1 : 0);
} catch (e) {
  sortir({ termine: false, erreurs: [String(e && e.message ? e.message : e)] }, 1);
}
