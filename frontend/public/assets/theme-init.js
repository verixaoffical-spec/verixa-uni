/* The saved theme is applied before the page draws, so it never flashes the wrong one.
   A separate file because the Content-Security-Policy in backend/main.py refuses inline scripts. */
try { if (localStorage.getItem('verixa-theme') === 'light') document.documentElement.dataset.theme = 'light'; } catch (e) {}
