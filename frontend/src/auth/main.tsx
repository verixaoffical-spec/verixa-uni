import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import AuthPage from './AuthPage';
import PasswordReset from './PasswordReset';
import VerifyEmail from './VerifyEmail';
import '../shared/site.css';
import './auth.css';

const resetPage = /^\/(forgot|reset)-password\/?$/.test(location.pathname);
const verifyPage = /^\/verify-email\/?$/.test(location.pathname);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {verifyPage ? <VerifyEmail /> : resetPage ? <PasswordReset /> : <AuthPage />}
  </StrictMode>,
);
