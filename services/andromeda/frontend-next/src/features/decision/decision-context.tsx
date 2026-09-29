"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  acceptDecisionSuggestion as apiAcceptDecisionSuggestion,
  addDecisionShortlist as apiAddDecisionShortlist,
  excludeDecisionProgram as apiExcludeDecisionProgram,
  getDecisionContext,
  getDecisionSuggestions,
  markDecisionProgramConsidered as apiMarkDecisionProgramConsidered,
  rejectDecisionSuggestion as apiRejectDecisionSuggestion,
  removeDecisionShortlist as apiRemoveDecisionShortlist,
  restoreDecisionShortlist as apiRestoreDecisionShortlist,
  restoreExcludedDecisionProgram as apiRestoreExcludedDecisionProgram,
  reopenDecisionFinalChoice as apiReopenDecisionFinalChoice,
  selectDecisionFinalChoice as apiSelectDecisionFinalChoice,
  setDecisionShortlistRole as apiSetDecisionShortlistRole,
  updateDecisionConstraints as apiUpdateDecisionConstraints,
  ApiError,
  ApiTimeoutError,
} from "@/lib/api";
import {
  normalizeDecisionContext,
  type ApiRevisionConflict,
  type DecisionConstraintsRequest,
  type DecisionContextData,
  type DecisionMutationResponse,
  type DecisionShortlistEntry,
  type DecisionSuggestionsData,
  type ShortlistRole,
  normalizeDecisionSuggestions,
} from "@/lib/types";
import { trackDecisionSessionStarted } from "@/lib/analytics";

type DecisionMutationOperation = (expectedRevision: number | null) => Promise<DecisionMutationResponse>;

export type DecisionContextValue = {
  context: DecisionContextData | null;
  suggestions: DecisionSuggestionsData | null;
  activeShortlist: DecisionShortlistEntry[];
  removedShortlist: DecisionShortlistEntry[];
  primaryShortlist: DecisionShortlistEntry[];
  alternativeShortlist: DecisionShortlistEntry[];
  isLoading: boolean;
  isSuggestionsLoading: boolean;
  isMutating: boolean;
  error: string | null;
  mutationError: string | null;
  conflict: ApiRevisionConflict | null;
  refresh: () => Promise<void>;
  refreshSuggestions: () => Promise<void>;
  clearMutationError: () => void;
  updateConstraints: (constraints: DecisionConstraintsRequest | null) => Promise<DecisionMutationResponse>;
  markConsidered: (programId: string) => Promise<DecisionMutationResponse>;
  addShortlist: (programId: string, role?: ShortlistRole) => Promise<DecisionMutationResponse>;
  removeShortlist: (programId: string) => Promise<DecisionMutationResponse>;
  restoreShortlist: (programId: string) => Promise<DecisionMutationResponse>;
  setRole: (programId: string, role: ShortlistRole) => Promise<DecisionMutationResponse>;
  exclude: (programId: string) => Promise<DecisionMutationResponse>;
  restoreExcluded: (programId: string) => Promise<DecisionMutationResponse>;
  acceptSuggestion: (programId: string, role?: ShortlistRole) => Promise<DecisionMutationResponse>;
  rejectSuggestion: (programId: string) => Promise<DecisionMutationResponse>;
  selectFinalChoice: (programId: string) => Promise<DecisionMutationResponse>;
  reopenFinalChoice: () => Promise<DecisionMutationResponse>;
};

const DecisionContextReact = createContext<DecisionContextValue | null>(null);

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ApiTimeoutError) return "Сервис выбора не ответил вовремя. Проверьте подключение и повторите попытку.";
  if (error instanceof ApiError) {
    if (error.status === 409) return "Выбор изменился в другой вкладке. Обновите данные и повторите действие.";
    if (error.status === 422) return "Проверьте введённые данные и повторите попытку.";
    if (error.status >= 500) return "Сервис выбора временно недоступен. Попробуйте ещё раз позже.";
  }
  return fallback;
}

/** Apply only the server mutation envelope; no client-side shortlist pruning is possible here. */
export function applyDecisionMutation(mutation: DecisionMutationResponse): DecisionContextData {
  return normalizeDecisionContext(mutation.context);
}

export function DecisionContextProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<DecisionContextData | null>(null);
  const [suggestions, setSuggestions] = useState<DecisionSuggestionsData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ApiRevisionConflict | null>(null);
  const contextRequestRef = useRef<Promise<void> | null>(null);
  const suggestionsRequestRef = useRef<Promise<void> | null>(null);
  const initialLoadRef = useRef<Promise<void> | null>(null);

  const refresh = useCallback((): Promise<void> => {
    if (contextRequestRef.current) return contextRequestRef.current;

    const request = (async () => {
      setIsLoading(true);
      setError(null);
      try {
        const next = await getDecisionContext();
        setContext(next);
        setConflict(null);
      } catch (cause) {
        // Anonymous sessions are supported by this endpoint. A 401 should
        // not turn every independent entry point into a blocked screen.
        if (!(cause instanceof ApiError && cause.status === 401)) {
          setError(describeError(cause, "Не удалось загрузить ваш выбор."));
        }
      } finally {
        setIsLoading(false);
      }
    })();

    contextRequestRef.current = request;
    void request.finally(() => {
      if (contextRequestRef.current === request) contextRequestRef.current = null;
    });
    return request;
  }, []);

  const refreshSuggestions = useCallback((): Promise<void> => {
    if (suggestionsRequestRef.current) return suggestionsRequestRef.current;

    const request = (async () => {
      setIsSuggestionsLoading(true);
      try {
        const next = await getDecisionSuggestions();
        // Suggestions are derived data. Refreshing them never mutates the
        // explicit shortlist kept in `context`.
        setSuggestions(normalizeDecisionSuggestions(next));
      } catch (cause) {
        setError(describeError(cause, "Не удалось получить предложения системы."));
      } finally {
        setIsSuggestionsLoading(false);
      }
    })();

    suggestionsRequestRef.current = request;
    void request.finally(() => {
      if (suggestionsRequestRef.current === request) suggestionsRequestRef.current = null;
    });
    return request;
  }, []);

  const runMutation = useCallback(async (operation: DecisionMutationOperation): Promise<DecisionMutationResponse> => {
    setIsMutating(true);
    setMutationError(null);
    setConflict(null);
    try {
      const result = await operation(context?.state.revision ?? null);
      setContext(applyDecisionMutation(result));
      // The previous suggestion set is tied to an older context revision.
      // Keep it only when the server explicitly returned the same revision.
      setSuggestions((current) => current && current.contextRevision === result.context.state.revision ? current : null);
      return result;
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        const conflictState: ApiRevisionConflict = {
          status: 409,
          message: "Выбор изменился в другой вкладке. Мы загрузили актуальное состояние; проверьте действие ещё раз.",
        };
        setConflict(conflictState);
        setMutationError(conflictState.message);
        await refresh();
      } else {
        setMutationError(describeError(cause, "Не удалось сохранить изменение выбора."));
      }
      throw cause;
    } finally {
      setIsMutating(false);
    }
  }, [context, refresh]);

  const updateConstraints = useCallback(
    (constraints: DecisionConstraintsRequest | null) =>
      runMutation((expectedRevision) => apiUpdateDecisionConstraints({ version: 1, constraints, expectedRevision })),
    [runMutation],
  );
  const markConsidered = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiMarkDecisionProgramConsidered(programId, expectedRevision)),
    [runMutation],
  );
  const addShortlist = useCallback(
    (programId: string, role: ShortlistRole = "primary") => runMutation((expectedRevision) => apiAddDecisionShortlist(programId, role, expectedRevision)),
    [runMutation],
  );
  const removeShortlist = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiRemoveDecisionShortlist(programId, expectedRevision)),
    [runMutation],
  );
  const restoreShortlist = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiRestoreDecisionShortlist(programId, expectedRevision)),
    [runMutation],
  );
  const setRole = useCallback(
    (programId: string, role: ShortlistRole) => runMutation((expectedRevision) => apiSetDecisionShortlistRole(programId, role, expectedRevision)),
    [runMutation],
  );
  const exclude = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiExcludeDecisionProgram(programId, expectedRevision)),
    [runMutation],
  );
  const restoreExcluded = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiRestoreExcludedDecisionProgram(programId, expectedRevision)),
    [runMutation],
  );
  const acceptSuggestion = useCallback(
    (programId: string, role: ShortlistRole = "primary") => runMutation((expectedRevision) => apiAcceptDecisionSuggestion(programId, role, expectedRevision)),
    [runMutation],
  );
  const rejectSuggestion = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiRejectDecisionSuggestion(programId, expectedRevision)),
    [runMutation],
  );
  const selectFinalChoice = useCallback(
    (programId: string) => runMutation((expectedRevision) => apiSelectDecisionFinalChoice(programId, expectedRevision)),
    [runMutation],
  );
  const reopenFinalChoice = useCallback(
    () => runMutation((expectedRevision) => apiReopenDecisionFinalChoice(expectedRevision)),
    [runMutation],
  );
  const clearMutationError = useCallback(() => {
    setMutationError(null);
    setConflict(null);
  }, []);

  useEffect(() => {
    if (!initialLoadRef.current) initialLoadRef.current = refresh();
  }, [refresh]);

  useEffect(() => {
    if (context) trackDecisionSessionStarted(context.decisionId);
  }, [context]);

  const activeShortlist = useMemo(
    () => (context?.state.choice.shortlistEntries ?? []).filter((entry) => entry.state === "active"),
    [context],
  );
  const removedShortlist = useMemo(
    () => (context?.state.choice.shortlistEntries ?? []).filter((entry) => entry.state === "removed"),
    [context],
  );
  const primaryShortlist = useMemo(() => activeShortlist.filter((entry) => entry.role === "primary"), [activeShortlist]);
  const alternativeShortlist = useMemo(() => activeShortlist.filter((entry) => entry.role === "alternative"), [activeShortlist]);

  const value = useMemo<DecisionContextValue>(() => ({
    context,
    suggestions,
    activeShortlist,
    removedShortlist,
    primaryShortlist,
    alternativeShortlist,
    isLoading,
    isSuggestionsLoading,
    isMutating,
    error,
    mutationError,
    conflict,
    refresh,
    refreshSuggestions,
    clearMutationError,
    updateConstraints,
    markConsidered,
    addShortlist,
    removeShortlist,
    restoreShortlist,
    setRole,
    exclude,
    restoreExcluded,
    acceptSuggestion,
    rejectSuggestion,
    selectFinalChoice,
    reopenFinalChoice,
  }), [
    context,
    suggestions,
    activeShortlist,
    removedShortlist,
    primaryShortlist,
    alternativeShortlist,
    isLoading,
    isSuggestionsLoading,
    isMutating,
    error,
    mutationError,
    conflict,
    refresh,
    refreshSuggestions,
    clearMutationError,
    updateConstraints,
    markConsidered,
    addShortlist,
    removeShortlist,
    restoreShortlist,
    setRole,
    exclude,
    restoreExcluded,
    acceptSuggestion,
    rejectSuggestion,
    selectFinalChoice,
    reopenFinalChoice,
  ]);

  return <DecisionContextReact.Provider value={value}>{children}</DecisionContextReact.Provider>;
}

export function useDecisionContext(): DecisionContextValue {
  const value = useContext(DecisionContextReact);
  if (!value) throw new Error("useDecisionContext must be used inside DecisionContextProvider");
  return value;
}
