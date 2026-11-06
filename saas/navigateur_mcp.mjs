#!/usr/bin/env node
// Navigateur d'une tâche « tester » : lance le serveur MCP Playwright pour l'agent, avec les comptes
// de test en secrets, limité aux domaines de l'application testée.
//
// Lancé par OpenCode (serveur MCP ajouté par l'application pour la durée de la tâche, POST /mcp).
// Variables reçues :
//   QAF_NAV_SECRETS   JSON {"COMPTE_1_IDENTIFIANT": "...", "COMPTE_1_MOT_DE_PASSE": "..."}
//   QAF_NAV_ORIGINES  domaines autorisés, séparés par « ; » (https://recette.exemple.com;https://sso.exemple.com)
//   QAF_NAV_VERSION   version de @playwright/mcp (figée)
//   PLAYWRIGHT_MCP_CLI (facultatif) chemin de cli.js de @playwright/mcp installé dans l'image
//
// Les secrets sont écrits dans un fichier temporaire lisible par ce seul utilisateur, lu par le MCP
// au démarrage, puis effacé. L'agent saisit le NOM d'un secret ; le MCP saisit la valeur et la
// remplace par <secret>NOM</secret> dans tout ce qu'il renvoie. Les captures nommées par l'agent sont
// écrites dans le dossier courant (la campagne).

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';

const secrets = JSON.parse(process.env.QAF_NAV_SECRETS || '{}');
const origines = (process.env.QAF_NAV_ORIGINES || '').split(';').filter(Boolean);
const version = process.env.QAF_NAV_VERSION || '0.0.84';
if (!origines.length) {
  process.stderr.write('QAF_NAV_ORIGINES manquant : le navigateur doit être limité à l\'application testée.\n');
  process.exit(2);
}

// dotenv : valeur entre guillemets simples, doubles ou obliques selon ce qu'elle contient.
const ligne = (nom, valeur) => {
  if (!/^[A-Z][A-Z0-9_]*$/.test(nom) || /[\r\n]/.test(valeur)) throw new Error(`secret invalide : ${nom}`);
  const q = ["'", '"', '`'].find((c) => !valeur.includes(c));
  if (!q) throw new Error(`secret ${nom} : caractères non pris en charge`);
  return `${nom}=${q}${valeur}${q}`;
};
// Fichiers de secrets laissés par un arrêt brutal d'une tâche précédente.
for (const n of fs.readdirSync(os.tmpdir())) {
  const p = path.join(os.tmpdir(), n);
  try { if (n.startsWith('qaf-nav-') && Date.now() - fs.statSync(p).mtimeMs > 60000) fs.rmSync(p, { recursive: true, force: true }); } catch { /* autre utilisateur */ }
}
const dossier = fs.mkdtempSync(path.join(os.tmpdir(), 'qaf-nav-'));
const fichier = path.join(dossier, 'secrets.env');
fs.writeFileSync(fichier, Object.entries(secrets).map(([n, v]) => ligne(n, String(v))).join('\n') + '\n', { mode: 0o600 });
const effacer = () => { try { fs.rmSync(dossier, { recursive: true, force: true }); } catch { /* déjà effacé */ } };

const options = [
  '--headless', '--isolated', '--browser', 'chromium', '--viewport-size', '1366x900',
  '--allowed-origins', origines.join(';'), '--secrets', fichier, '--output-dir', path.resolve('captures'),
  '--image-responses', 'omit',
];
let commande, args;
let cli = process.env.PLAYWRIGHT_MCP_CLI;
if (!cli) {
  try { cli = createRequire(import.meta.url).resolve('@playwright/mcp/cli.js'); } catch { cli = ''; }
}
if (cli) {
  commande = process.execPath;
  args = [cli, ...options];
} else {
  commande = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  args = ['-y', `@playwright/mcp@${version}`, ...options];
}
const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('QAF_')));
const enfant = spawn(commande, args, { stdio: 'inherit', env, shell: process.platform === 'win32' && !cli });
// Le MCP lit ses secrets au démarrage : le fichier disparaît quelques secondes après, et dans tous les cas à la fin.
setTimeout(effacer, 8000).unref();
enfant.on('exit', (code) => { effacer(); process.exit(code ?? 1); });
for (const s of ['SIGINT', 'SIGTERM']) process.on(s, () => { enfant.kill(s); });
