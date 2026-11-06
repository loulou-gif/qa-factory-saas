import { defineConfig, devices, type ReporterDescription } from '@playwright/test';
import env from './config/env';

// Lancé depuis QA Factory : le navigateur ne joint que les domaines de l'application testée
// (QAF_HOTES_AUTORISES, séparés par « ; »). Sans cette variable, aucune restriction.
const hotesAutorises = (process.env.QAF_HOTES_AUTORISES || '').split(';').map((h) => h.trim()).filter(Boolean);
const restrictionReseau = hotesAutorises.length
  ? [`--host-resolver-rules=MAP * ~NOTFOUND, ${hotesAutorises.map((h) => `EXCLUDE ${h}`).join(', ')}`]
  : [];

// Allure seulement s'il est installé (npm install) : l'exécution depuis QA Factory impose ses propres rapports.
function installe(module: string): boolean {
  try {
    require.resolve(module);
    return true;
  } catch {
    return false;
  }
}

const rapporteurs: ReporterDescription[] = [['list']];
if (installe('allure-playwright')) {
  rapporteurs.push(['allure-playwright', { outputFolder: 'allure-results', detail: true, screenshots: true }]);
}
rapporteurs.push(['./utils/evidence-reporter.js', { outputFolder: 'evidence' }]);

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: rapporteurs,
  use: {
    baseURL: env.baseUrl,
    locale: 'fr-FR',
    trace: 'retain-on-failure',
    // Chaque test garde une capture de son état final comme preuve d'exécution.
    screenshot: { mode: 'on', fullPage: true },
    video: 'retain-on-failure',
    launchOptions: { args: restrictionReseau },
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
