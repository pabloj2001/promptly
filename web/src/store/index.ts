import { create } from "zustand";

// Small cross-cutting UI state (04). Server data lives in React Query.
interface UiState {
  activeProject: string | null;
  selectedTaskId: string | null;
  setActiveProject: (name: string | null) => void;
  setSelectedTaskId: (id: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeProject: null,
  selectedTaskId: null,
  setActiveProject: (name) => set({ activeProject: name }),
  setSelectedTaskId: (id) => set({ selectedTaskId: id }),
}));

// Non-hook accessor so the API client can read the active project outside React.
export const getActiveProject = () => useUiStore.getState().activeProject;
