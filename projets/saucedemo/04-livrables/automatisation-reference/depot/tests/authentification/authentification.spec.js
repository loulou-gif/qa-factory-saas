const { test, expect } = require('@playwright/test');
const env = require('../../config/env');
const { AuthentificationPage } = require('../../pages/authentification.page');

test.describe('Authentification @authentification', () => {
  test('[CT0001] Se connecter avec un compte valide @authentification', async ({ page }) => {
    const connexion = new AuthentificationPage(page);
    await test.step("Ouvrir le lien de l'application", async () => {
      await connexion.ouvrir();
      await expect(connexion.champIdentifiant).toBeVisible();
      await expect(connexion.champMotDePasse).toBeVisible();
      await expect(connexion.boutonConnexion).toBeVisible();
    });
    await test.step("Renseigner le nom d'utilisateur et le mot de passe du compte JDD-001", async () => {
      await connexion.renseigner(env.compte(1).identifiant, env.compte(1).motDePasse);
      await expect(connexion.champMotDePasse).toHaveAttribute('type', 'password');
    });
    await test.step('Cliquer sur le bouton de connexion', async () => {
      await connexion.valider();
      await expect(connexion.titrePage).toHaveText('Products');
      await expect(connexion.articles.first()).toBeVisible();
    });
  });

  test("[CT0002] Bloquer la connexion sans nom d'utilisateur @authentification", async ({ page }) => {
    const connexion = new AuthentificationPage(page);
    await connexion.ouvrir();
    await test.step("Laisser le champ nom d'utilisateur vide et renseigner le mot de passe", async () => {
      await connexion.renseigner('', env.compte(1).motDePasse);
      await expect(connexion.champIdentifiant).toHaveValue('');
    });
    await test.step('Cliquer sur le bouton de connexion', async () => {
      await connexion.valider();
      await expect(connexion.messageErreur).toHaveText('Epic sadface: Username is required');
      await expect(connexion.boutonConnexion).toBeVisible();
    });
  });

  test('[CT0003] Bloquer la connexion sans mot de passe @authentification', async ({ page }) => {
    const connexion = new AuthentificationPage(page);
    await connexion.ouvrir();
    await test.step("Renseigner le nom d'utilisateur et laisser le champ mot de passe vide", async () => {
      await connexion.renseigner(env.compte(1).identifiant, '');
      await expect(connexion.champMotDePasse).toHaveValue('');
    });
    await test.step('Cliquer sur le bouton de connexion', async () => {
      await connexion.valider();
      await expect(connexion.messageErreur).toHaveText('Epic sadface: Password is required');
      await expect(connexion.boutonConnexion).toBeVisible();
    });
  });
});
