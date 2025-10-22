import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { AuthCredentials } from '../services/api';
import { authApi, getActiveCredentials, setAuthCredentials } from '../services/api';
import type { AuthUser } from '../types';

type AuthStatus = 'loading' | 'ready';

interface AuthContextValue {
  status: AuthStatus;
  requireAuth: boolean;
  isAuthenticated: boolean;
  user: AuthUser | null;
  credentials: AuthCredentials | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const STORAGE_KEY = 'podly-auth-credentials';

const readStoredCredentials = (): AuthCredentials | null => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as AuthCredentials;
    if (typeof parsed?.username === 'string' && typeof parsed?.password === 'string') {
      return parsed;
    }
    return null;
  } catch (error) {
    console.warn('Failed to read stored credentials', error);
    return null;
  }
};

const persistCredentials = (credentials: AuthCredentials | null) => {
  try {
    if (!credentials) {
      window.localStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(credentials));
  } catch (error) {
    console.warn('Failed to persist credentials', error);
  }
};

interface InternalState {
  status: AuthStatus;
  requireAuth: boolean;
  user: AuthUser | null;
  credentials: AuthCredentials | null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<InternalState>({
    status: 'loading',
    requireAuth: false,
    user: null,
    credentials: null,
  });

  const bootstrapAuth = useCallback(async () => {
    try {
      const statusResponse = await authApi.getStatus();
      const requireAuth = Boolean(statusResponse.require_auth);

      if (!requireAuth) {
        setAuthCredentials(null);
        persistCredentials(null);
        setState({
          status: 'ready',
          requireAuth: false,
          user: null,
          credentials: null,
        });
        return;
      }

      const stored = readStoredCredentials();
      if (!stored) {
        setAuthCredentials(null);
        setState({
          status: 'ready',
          requireAuth: true,
          user: null,
          credentials: null,
        });
        return;
      }

      setAuthCredentials(stored);
      try {
        const me = await authApi.getCurrentUser();
        setState({
          status: 'ready',
          requireAuth: true,
          user: me.user,
          credentials: stored,
        });
      } catch (error) {
        console.warn('Stored credentials rejected, clearing cache', error);
        setAuthCredentials(null);
        persistCredentials(null);
        setState({
          status: 'ready',
          requireAuth: true,
          user: null,
          credentials: null,
        });
      }
    } catch (error) {
      console.error('Failed to initialize auth state', error);
      setState({
        status: 'ready',
        requireAuth: false,
        user: null,
        credentials: null,
      });
    }
  }, []);

  useEffect(() => {
    void bootstrapAuth();
  }, [bootstrapAuth]);

  const login = useCallback(async (username: string, password: string) => {
    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      throw new Error('Username is required.');
    }

    const response = await authApi.login(trimmedUsername, password);
    const credentials: AuthCredentials = { username: trimmedUsername, password };
    setAuthCredentials(credentials);
    persistCredentials(credentials);

    setState({
      status: 'ready',
      requireAuth: true,
      user: response.user,
      credentials,
    });
  }, []);

  const logout = useCallback(() => {
    setAuthCredentials(null);
    persistCredentials(null);
    setState((prev) => ({
      status: 'ready',
      requireAuth: prev.requireAuth,
      user: prev.requireAuth ? null : prev.user,
      credentials: null,
    }));
  }, []);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });

      const active = getActiveCredentials();
      const username = active?.username ?? state.credentials?.username;
      if (!username) {
        return;
      }

      const updatedCredentials: AuthCredentials = { username, password: newPassword };
      setAuthCredentials(updatedCredentials);
      persistCredentials(updatedCredentials);
      setState((prev) => ({
        ...prev,
        credentials: updatedCredentials,
      }));
    },
    [state.credentials],
  );

  const refreshUser = useCallback(async () => {
    if (!state.requireAuth) {
      return;
    }
    const me = await authApi.getCurrentUser();
    setState((prev) => ({
      ...prev,
      user: me.user,
    }));
  }, [state.requireAuth]);

  const value = useMemo<AuthContextValue>(() => {
    const isAuthenticated = !state.requireAuth || Boolean(state.user);
    return {
      status: state.status,
      requireAuth: state.requireAuth,
      isAuthenticated,
      user: state.user,
      credentials: state.credentials,
      login,
      logout,
      changePassword,
      refreshUser,
    };
  }, [changePassword, login, logout, refreshUser, state.credentials, state.requireAuth, state.status, state.user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
