// Page de connexion de SauceDemo : locators et interactions, aucune assertion.
class AuthentificationPage {
  constructor(page) {
    this.page = page;
    this.champIdentifiant = page.locator('[data-test="username"]');
    this.champMotDePasse = page.locator('[data-test="password"]');
    this.boutonConnexion = page.locator('[data-test="login-button"]');
    this.messageErreur = page.locator('[data-test="error"]');
    this.titrePage = page.locator('[data-test="title"]');
    this.articles = page.locator('[data-test="inventory-item"]');
  }

  async ouvrir() {
    await this.page.goto('/');
  }

  async renseigner(identifiant, motDePasse) {
    await this.champIdentifiant.fill(identifiant);
    await this.champMotDePasse.fill(motDePasse);
  }

  async valider() {
    await this.boutonConnexion.click();
  }
}

module.exports = { AuthentificationPage };
