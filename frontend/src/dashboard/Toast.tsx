import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

export interface ToastAction {
  label: string;
  run: () => void;
}

type ShowToast = (message: string, action?: ToastAction) => void;

const ToastContext = createContext<ShowToast>(() => {});

// Shows a short message at the bottom of the screen: const toast = useToast(); toast('Saved')
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState('');
  const [action, setAction] = useState<ToastAction>();
  const [visible, setVisible] = useState(false);
  const timer = useRef(0);

  const show = useCallback<ShowToast>((text, withAction) => {
    setMessage(text);
    setAction(withAction);
    setVisible(true);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setVisible(false), withAction ? 6000 : 3200);  // longer when there is a button
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={'toast' + (visible ? ' on' : '')} role="status" aria-live="polite">
        <span>{message}</span>
        {action && <button onClick={() => { action.run(); setVisible(false); }}>{action.label}</button>}
      </div>
    </ToastContext.Provider>
  );
}
