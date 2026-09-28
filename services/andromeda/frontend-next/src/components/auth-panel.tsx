"use client";

import { useEffect, useState } from "react";
import { UserRound, LogIn, UserPlus, LogOut, ChevronDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getAuthSession, registerAccount, loginAccount, logoutAccount, importGuestDecision } from "@/lib/api";
import type { AuthSession } from "@/lib/types";
import type { View } from "@/lib/router";

export function AuthPanel({ onNavigate }: { onNavigate: (view: View) => void }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"login" | "register">("login");
  const [transferNotice, setTransferNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getAuthSession()
      .then((s) => active && setSession(s))
      .catch(() => active && setSession({ authenticated: false, account: null }));
    return () => {
      active = false;
    };
  }, []);

  const submit = async () => {
    setError(null);
    if (!email || !password) {
      setError("Заполните email и пароль.");
      return;
    }
    if (tab === "register" && password.length < 12) {
      setError("Пароль для регистрации — минимум 12 символов.");
      return;
    }
    setBusy(true);
    try {
      const next = tab === "register" ? await registerAccount({ email, password }) : await loginAccount({ email, password });
      setSession(next);
      if (next.decisionTransfer === "account_state_kept") {
        setTransferNotice("У аккаунта уже есть свой выбор. Гостевой shortlist сохранён отдельно — импортировать его можно явно.");
      }
      setOpen(false);
      setPassword("");
      onNavigate("account");
    } catch {
      setError("Не удалось выполнить запрос. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      const next = await logoutAccount();
      setSession(next);
    } finally {
      setBusy(false);
    }
  };

  const importGuest = async () => {
    setBusy(true);
    try {
      const next = await importGuestDecision();
      setSession(next);
      setTransferNotice("Гостевой shortlist импортирован в аккаунт. Решение сохранено между устройствами.");
    } catch {
      setTransferNotice("Не удалось импортировать гостевой shortlist. Текущий выбор аккаунта не изменён.");
    } finally {
      setBusy(false);
    }
  };

  if (!session) {
    return (
      <div data-testid="auth-panel">
        <Button variant="outline" size="sm" disabled className="gap-2" aria-label="Профиль">
          <Loader2 className="h-4 w-4 animate-spin" />
        </Button>
      </div>
    );
  }

  if (session.authenticated && session.account) {
    return (
      <div data-testid="auth-panel">
        <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="gap-2 rounded-full" data-testid="profile-menu-trigger">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-primary text-primary-foreground">
              <UserRound className="h-3.5 w-3.5" />
            </span>
            <span className="max-w-[120px] truncate">{session.account.displayName ?? session.account.email}</span>
            <ChevronDown className="h-3.5 w-3.5 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56" data-testid="profile-menu-panel">
          <DropdownMenuLabel className="truncate" data-testid="auth-account">{session.account.email}</DropdownMenuLabel>
          {transferNotice && <DropdownMenuLabel className="whitespace-normal text-xs font-normal text-amber-700">{transferNotice}</DropdownMenuLabel>}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => onNavigate("account")}>
            <UserRound className="mr-2 h-4 w-4" /> Личный кабинет
          </DropdownMenuItem>
          {session.decisionTransfer === "account_state_kept" && (
            <DropdownMenuItem onClick={() => void importGuest()} disabled={busy}>
              Импортировать гостевой shortlist
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={logout} disabled={busy} data-testid="auth-logout">
            <LogOut className="mr-2 h-4 w-4" /> Выйти
          </DropdownMenuItem>
        </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  }

  return (
    <div data-testid="auth-panel">
      <Button data-testid="profile-menu-trigger" size="sm" className="gap-2 rounded-full bg-primary text-primary-foreground hover:bg-primary/90" onClick={() => setOpen(true)}>
        <UserRound className="h-4 w-4" /> Войти
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif">Вход и регистрация</DialogTitle>
            <DialogDescription>
              Гостевая сессия уже активна — можно пройти тест и смотреть рекомендации без регистрации. Аккаунт
              сохранит профиль между устройствами.
            </DialogDescription>
          </DialogHeader>
          <Tabs value={tab} onValueChange={(v) => setTab(v as "login" | "register")}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="login" data-testid="auth-login-trigger">Войти</TabsTrigger>
              <TabsTrigger value="register" data-testid="auth-register-trigger">Создать аккаунт</TabsTrigger>
            </TabsList>
            <TabsContent value="login" className="space-y-3 pt-2">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" data-testid="auth-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pwd">Пароль</Label>
                <Input id="pwd" data-testid="auth-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </TabsContent>
            <TabsContent value="register" className="space-y-3 pt-2">
              <div className="space-y-1.5">
                <Label htmlFor="email2">Email</Label>
                <Input id="email2" data-testid="auth-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pwd2">Пароль (минимум 12 символов)</Label>
                <Input id="pwd2" data-testid="auth-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </TabsContent>
          </Tabs>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button variant="outline" data-testid="auth-guest" onClick={() => setOpen(false)}>
              Продолжить как гость
            </Button>
            <Button data-testid="auth-submit" onClick={submit} disabled={busy} className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90">
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {tab === "login" ? "Войти" : "Зарегистрироваться"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function AuthPanelTrigger({ onOpen }: { onOpen: () => void }) {
  return (
    <Button size="sm" className="gap-2 rounded-full bg-primary text-primary-foreground hover:bg-primary/90" onClick={onOpen}>
      <UserPlus className="h-4 w-4" /> Войти
    </Button>
  );
}
