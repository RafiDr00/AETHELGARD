/**
 * Aethelgard — Global UI State (Zustand)
 *
 * Central store for all client-side UI state.
 * Server state lives in TanStack Query — this store owns only pure UI concerns.
 */
import { create } from "zustand";

interface UiState {
  // ── Sidebar ──────────────────────────────────────────────────────────────
  sidebarExpanded: boolean;
  toggleSidebar:         () => void;
  setSidebarExpanded:    (v: boolean) => void;

  // ── Dashboard job selection ───────────────────────────────────────────────
  selectedJobId:    string | null;
  setSelectedJobId: (id: string | null) => void;

  // ── Pipeline stage replay ─────────────────────────────────────────────────
  stageReplayIndex:    number | null;
  setStageReplayIndex: (idx: number | null) => void;

  // ── Active overlay panel ──────────────────────────────────────────────────
  activePanel:    string | null;
  setActivePanel: (id: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  // Sidebar  — starts expanded
  sidebarExpanded:   true,
  toggleSidebar:     () => set((s) => ({ sidebarExpanded: !s.sidebarExpanded })),
  setSidebarExpanded: (v) => set({ sidebarExpanded: v }),

  // Dashboard
  selectedJobId:    null,
  setSelectedJobId: (id) => set({ selectedJobId: id }),

  // Replay
  stageReplayIndex:    null,
  setStageReplayIndex: (idx) => set({ stageReplayIndex: idx }),

  // Active panel
  activePanel:    null,
  setActivePanel: (id) => set({ activePanel: id }),
}));
