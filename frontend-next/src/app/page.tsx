"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { useRouter } from "@/lib/router";
import { getPrograms } from "@/lib/api";
import type { ProgramSummary } from "@/lib/types";
import { CatalogPage } from "@/features/catalog/catalog-page";
import { ProgramPage } from "@/features/program/program-page";
import { ComparePage } from "@/features/compare/compare-page";
import { ProftestPage } from "@/features/proftest/proftest-page";
import { RecommendationsPage } from "@/features/recommendations/recommendations-page";
import { EventsPage } from "@/features/events/events-page";
import { EventPage } from "@/features/events/event-page";
import { PersonalRoutePage } from "@/features/personal-route/personal-route-page";
import { UnifiedFlowPage } from "@/features/unified-flow/unified-flow-page";
import { AccountPage } from "@/features/account/account-page";
import { OpsPage } from "@/features/ops/ops-page";
import { DecisionContextProvider } from "@/features/decision/decision-context";
import { DecisionPage } from "@/features/decision/decision-page";
import { HomePage } from "@/features/home/home-page";
import { AdmissionPage } from "@/features/admission/admission-page";
import { UniversityAdminPage } from "@/features/university-admin/university-admin-page";
import { UniversityCatalogPage } from "@/features/university/university-catalog-page";
import { AssistantPage } from "@/features/assistant/assistant-page";
import { KnowledgeReviewPage } from "@/features/knowledge-review/knowledge-review-page";

export default function Page() {
  const { route, navigate } = useRouter();
  const [programs, setPrograms] = useState<ProgramSummary[]>([]);
  const [programsLoading, setProgramsLoading] = useState(true);
  const [programsError, setProgramsError] = useState<string | null>(null);

  const loadPrograms = useCallback(() => {
    setProgramsLoading(true);
    setProgramsError(null);
    getPrograms()
      .then((res) => setPrograms(res.items))
      .catch(() => setProgramsError("Не удалось загрузить каталог программ из API."))
      .finally(() => setProgramsLoading(false));
  }, []);

  useEffect(() => {
    if (route.view === "catalog" || route.view === "compare") void loadPrograms();
  }, [loadPrograms, route.view]);

  return (
    <DecisionContextProvider>
      <AppShell route={route} navigate={navigate}>
        {route.view === "home" && <HomePage navigate={navigate} />}
        {route.view === "assistant" && <AssistantPage navigate={navigate} />}
        {route.view === "decision" && <DecisionPage navigate={navigate} />}
        {route.view === "catalog" && (
          <CatalogPage programs={programs} loading={programsLoading} error={programsError} onRetry={loadPrograms} navigate={navigate} />
        )}
        {route.view === "program" && (
          <ProgramPage id={route.id ?? programs[0]?.id ?? ""} navigate={navigate} />
        )}
        {route.view === "compare" && (
          <ComparePage programs={programs} navigate={navigate} />
        )}
        {route.view === "proftest" && <ProftestPage navigate={navigate} />}
        {route.view === "admission" && <AdmissionPage navigate={navigate} />}
        {route.view === "recommendations" && <RecommendationsPage navigate={navigate} />}
        {route.view === "events" && <EventsPage initialUniversityId={route.id} navigate={navigate} />}
        {route.view === "event" && <EventPage id={route.id ?? ""} origin={route.origin} universityId={route.universityId} navigate={navigate} />}
        {route.view === "personal-route" && <PersonalRoutePage navigate={navigate} />}
        {route.view === "flow" && <UnifiedFlowPage navigate={navigate} />}
        {route.view === "account" && <AccountPage navigate={navigate} />}
        {route.view === "ops" && <OpsPage />}
        {route.view === "university-admin" && <UniversityAdminPage requestedUniversityId={route.id} navigate={navigate} />}
        {route.view === "knowledge-review" && <KnowledgeReviewPage navigate={navigate} />}
        {route.view === "university-catalog" && <UniversityCatalogPage universityId={route.id} navigate={navigate} />}
      </AppShell>
    </DecisionContextProvider>
  );
}
