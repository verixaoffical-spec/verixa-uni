// Dark is the default. index.html applies a saved choice before the page draws, so it never flashes the wrong theme.

export type Theme = 'dark' | 'light';
const KEY = 'verixa-theme';

export const currentTheme = (): Theme => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');

export function saveTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage can be blocked. The theme still changes for this visit.
  }
}
