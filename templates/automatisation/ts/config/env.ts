// Configuration centralisée : URL et comptes de test viennent du .env (non versionné)
// ou des variables d'environnement. Aucune valeur secrète par défaut.
import * as fs from 'fs';
import * as path from 'path';

function loadDotEnv(): void {
  const envPath = path.resolve(__dirname, '..', '.env');
  if (!fs.existsSync(envPath)) return;
  for (const rawLine of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const separator = line.indexOf('=');
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadDotEnv();

export interface Compte {
  identifiant: string;
  motDePasse: string;
}

// Compte de test n° numero (COMPTE_<n>_IDENTIFIANT / COMPTE_<n>_MOT_DE_PASSE).
// Le compte 1 accepte aussi APP_USERNAME / APP_PASSWORD.
export function compte(numero = 1): Compte {
  const n = Number(numero);
  return {
    identifiant: process.env[`COMPTE_${n}_IDENTIFIANT`] || (n === 1 ? process.env.APP_USERNAME || '' : ''),
    motDePasse: process.env[`COMPTE_${n}_MOT_DE_PASSE`] || (n === 1 ? process.env.APP_PASSWORD || '' : ''),
  };
}

const env = {
  baseUrl: process.env.BASE_URL || '',
  compte,
  isConfigured(): boolean {
    return Boolean(this.baseUrl && compte(1).identifiant && compte(1).motDePasse);
  },
};

export default env;
