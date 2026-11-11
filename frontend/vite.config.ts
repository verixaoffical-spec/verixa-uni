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
        if (['/login', '/signup', '/forgot-password', '/reset-password', '/verify-email'].includes(path)) req.url = '/auth.html' + (query ? '?' + query : '');
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
      '/api': { target: BACKEND, ws: true },  // ws: the live status WebSocket at /api/live
      '^/auth/': BACKEND,
      '/webhooks': BACKEND,
    },
  },
});
