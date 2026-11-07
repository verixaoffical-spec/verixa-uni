import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import AuthPage from './AuthPage';
import PasswordReset from './PasswordReset';
import '../shared/site.css';
import './auth.css';

const resetPage = /^\/(forgot|reset)-password\/?$/.test(location.pathname);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {resetPage ? <PasswordReset /> : <AuthPage />}
  </StrictMode>,
);
