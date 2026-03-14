import { create } from "zustand";

interface AuthState {
  apiKey: string | null;
  setApiKey: (key: string) => void;
  clearApiKey: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  apiKey: null,
  setApiKey: (key) => set({ apiKey: key.trim() }),
  clearApiKey: () => set({ apiKey: null }),
  isAuthenticated: () => {
    const key = get().apiKey;
    return key !== null && key.length > 0;
  },
}));
