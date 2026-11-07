import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// The FastAPI server. `npm run dev` forwards API calls to it, so the session cookie works on the dev server too.
const BACKEND = 'http://localhost:8000';

// FastAPI serves auth.html at /login and /signup. The dev server does the same.
function loginPages(): Plugin {
  return {
    name: 'verixa-login-pages',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const [path, query] = (req.url ?? '').split('?');
        if (path === '/login' || path === '/signup') req.url = '/auth.html' + (query ? '?' + query : '');
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), loginPages()],
  build: {
    // Three separate pages, each with its own entry file in src/
    rollupOptions: {
      input: { landing: 'index.html', auth: 'auth.html', dashboard: 'verixa_prototype.html' },
    },
  },
  server: {
    proxy: {
      '/api': BACKEND,
      '^/auth/': BACKEND,
      '/webhooks': BACKEND,
    },
  },
});
