export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

export const kb = (n: number) =>
  n < 1048576 ? (n / 1024).toFixed(n < 10240 ? 1 : 0) + ' KB' : (n / 1048576).toFixed(1) + ' MB';

// Size in bytes of text once saved as UTF-8
export const bytes = (s: string) => new TextEncoder().encode(s).length;

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
