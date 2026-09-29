"use client";

import { ArrowRight, BookOpen, CheckCircle2, GitCompare, GraduationCap, ListChecks, MessageCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, Tag } from "@/components/shared";
import { useDecisionContext } from "@/features/decision/decision-context";
import type { Route } from "@/lib/router";

const ENTRY_POINTS = [
  {
    view: "assistant" as const,
    icon: MessageCircle,
    title: "Задать вопрос",
    description: "Спросите, где больше математики, программирования или AI, сравните программы и разберите поступление.",
    action: "Открыть ассистента",
  },
  {
    view: "admission" as const,
    icon: GraduationCap,
    title: "Куда я могу поступить",
    description: "Введите известные баллы и ограничения, чтобы увидеть реалистичные, пограничные и рискованные варианты.",
    action: "Проверить поступление",
  },
  {
    view: "decision" as const,
    icon: ListChecks,
    title: "Помогите сузить выбор",
    description: "Посмотрите небольшой набор кандидатов и решите сами, что оставить в основных вариантах или альтернативах.",
    action: "Сформировать shortlist",
  },
  {
    view: "compare" as const,
    icon: GitCompare,
    title: "Сравнить программы",
    description: "Если у вас уже есть варианты, сразу сопоставьте содержание, поступление и trade-offs.",
    action: "Открыть сравнение",
  },
] as const;

export function HomePage({ navigate }: { navigate: (route: Route) => void }) {
  const { activeShortlist, isLoading } = useDecisionContext();
  return (
    <div data-testid="home-page" className="space-y-8">
      <PageHeader
        eyebrow="Andromeda · выбор программы"
        title="Что вы хотите понять?"
        description="Соберите небольшой осмысленный shortlist из реальных программ поддерживаемых университетов. Можно начать с любого сценария — профтест не обязателен."
        actions={<Tag tone="muted">Можно продолжить как гость</Tag>}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {ENTRY_POINTS.map(({ view, icon: Icon, title, description, action }) => (
          <Card key={view} className="group flex flex-col border-border/70 transition hover:-translate-y-0.5 hover:shadow-md">
            <CardContent className="flex flex-1 flex-col gap-4 p-5">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></span>
              <div>
                <h2 className="font-serif text-xl font-semibold">{title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
              </div>
              <Button type="button" variant="outline" className="mt-auto justify-between gap-2" onClick={() => navigate({ view })}>
                {action}<ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-center">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-background text-primary"><BookOpen className="h-5 w-5" /></div>
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-xl font-semibold">Продолжить мой выбор</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {isLoading ? "Проверяем сохранённый shortlist…" : activeShortlist.length > 0 ? `У вас сохранено программ: ${activeShortlist.length}. Решение хранится в анонимной сессии и доступно после перезагрузки.` : "Сохранённых программ пока нет — можно начать с каталога."}
            </p>
          </div>
          <Button type="button" onClick={() => navigate({ view: activeShortlist.length > 0 ? "decision" : "catalog" })} className="gap-2">
            {activeShortlist.length > 0 ? "Открыть мой выбор" : "Открыть каталог"}<ArrowRight className="h-4 w-4" />
          </Button>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        <span>Система предлагает, вы решаете. Ни одна программа не исчезает из shortlist без явного действия.</span>
        <Button type="button" variant="link" size="sm" onClick={() => navigate({ view: "catalog" })}>Посмотреть каталог</Button>
      </div>
    </div>
  );
}
