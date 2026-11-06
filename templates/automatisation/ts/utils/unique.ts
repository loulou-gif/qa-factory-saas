// Suffixe unique pour les données créées par les tests (évite les collisions et
// permet de reconnaître les données de test dans l'environnement).
export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function qaLabel(base: string): string {
  return `QA ${base} ${uniqueSuffix()}`;
}
