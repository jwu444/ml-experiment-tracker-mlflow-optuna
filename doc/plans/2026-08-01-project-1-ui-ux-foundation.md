# UI/UX Design Foundation (Issue #11, Slice A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the frontend a tokenized, accessible component foundation (design tokens, a small `ui/` primitive library, dark mode, an app shell, loading skeletons) and restyle the existing Upload + Chat pages onto it — no new features, no backend changes.

**Architecture:** A CSS-variable token layer (`styles/`) plus a `ui/` component library sit under the existing React Router pages. A `ThemeProvider` sets `data-theme` on `<html>`; every primitive reads tokens via CSS modules and exposes its semantics through roles / `data-*` / ARIA (never through class names, since tests run with CSS disabled). `AppShell` frames both routes. Radix supplies the one accessible interactive primitive shipped now (`Dialog`).

**Tech Stack:** React 18 + TypeScript (strict), Vite, Vitest + React Testing Library, CSS Modules, `@radix-ui/react-dialog` (the sole new dependency).

## Global Constraints

- **TypeScript strict:** `npm run type-check` (tsc `--noEmit`) must stay clean.
- **Exactly one new runtime dependency:** `@radix-ui/react-dialog`. No other new deps. **No web fonts** — system font stack only.
- **No backend changes.** Frontend-only slice.
- **No new features.** Deferred to later slices: drag-drop, upload progress, dataset preview/type badges (B); timestamps, copy button, scroll-to-bottom, chart captions/zoom/download (C); sidebar, recent chats, breadcrumb, `Cmd+K` (D); streaming (own issue). Do not implement these.
- **Preserve existing behavior and test hooks.** These selectors must keep working: file input `aria-label="CSV files"`, button name `"Upload"`, textarea `aria-label="Question"`, submit button name `"Ask"` / `"Asking…"`, `role="alert"` errors, `aria-label="Attached datasets"`, `<summary>"Raw statistics"`.
- **Tests never assert CSS-module class names.** Vitest runs with `css: false`, so `styles.x` is `undefined` in tests. Assert on `role`, accessible name, visible text, or `data-*` attributes only.
- **Accessibility:** all interactive primitives get a `:focus-visible` ring; accent text on the light background uses `--accent-text` (darker) so normal text clears WCAG AA 4.5:1; button fills use a teal dark enough that white text on it clears AA.
- **Direction C token values** are fixed by the spec (`doc/project-1-ui-ux-foundation-design.md`) and reproduced verbatim in Task 1.
- **Gates before every commit:** the task's own tests pass, plus `npm run type-check`. Run the full `npm test` at least at each task boundary.

---

### Task 1: Design tokens & global stylesheet

Create the token layer and migrate the existing global styles (including the `.markdown` rules `ChatTurn` depends on) onto tokens. This is a pure-asset task — its verification is build + existing tests staying green, not a new unit test.

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx` (swap `./index.css` import for the two new files)
- Delete: `frontend/src/index.css`

**Interfaces:**
- Produces: CSS custom properties available globally — colors (`--bg`, `--surface`, `--ink`, `--muted`, `--line`, `--accent`, `--accent-text`, `--accent-ink`, `--danger`, `--success`, `--warn`), type scale (`--text-xs…--text-2xl`, `--weight-normal/medium/semibold/bold`), spacing (`--space-1…--space-8`), radii (`--radius-sm/md/lg`). Dark values under `:root[data-theme="dark"]`.

- [x] **Step 1: Write `styles/tokens.css`**

```css
:root {
  /* color — Direction C (warm friendly), light */
  --bg: #faf7f4;
  --surface: #fffdfb;
  --ink: #232022;
  --muted: #736e6a;
  --line: #ece7e2;
  --accent: #0b7d70;        /* fill: dark enough that #fff text clears AA (4.5:1) */
  --accent-text: #0f766e;   /* accent-colored text on --bg */
  --accent-ink: #ffffff;    /* text/icon on --accent fills */
  --danger: #c0392b;
  --success: #1a7a4a;
  --warn: #a5631a;

  /* type scale */
  --text-xs: 12px;
  --text-sm: 13px;
  --text-base: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 26px;
  --weight-normal: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;

  /* spacing */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* radius */
  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 14px;

  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}

:root[data-theme="dark"] {
  --bg: #1a1715;
  --surface: #221e1b;
  --ink: #f2ede8;
  --muted: #a89f97;
  --line: #322c28;
  --accent: #2dd4bf;
  --accent-text: #5eead4;
  --accent-ink: #0b1a18;
  --danger: #e06a5c;
  --success: #4ecb8a;
  --warn: #d9a441;
}
```

- [x] **Step 2: Write `styles/global.css`** (migrates the old base + `.markdown` rules onto tokens)

```css
:root {
  font-family: var(--font-sans);
  line-height: 1.5;
  color: var(--ink);
  background: var(--bg);
  color-scheme: light dark;
}
body { margin: 0; }
img { max-width: 100%; height: auto; }

:where(button, a, input, textarea, [tabindex]):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Rendered Markdown in assistant replies (preserved from index.css). */
.markdown > :first-child { margin-top: 0; }
.markdown > :last-child { margin-bottom: 0; }
.markdown h1, .markdown h2, .markdown h3 {
  font-size: var(--text-lg);
  margin: var(--space-4) 0 var(--space-2);
}
.markdown code {
  font-family: var(--font-mono);
  font-size: 0.9em;
  background: color-mix(in srgb, var(--muted) 15%, transparent);
  padding: 0.1em 0.3em;
  border-radius: var(--radius-sm);
}
.markdown pre {
  background: color-mix(in srgb, var(--muted) 15%, transparent);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  overflow-x: auto;
}
.markdown pre code { background: none; padding: 0; }
.markdown table { border-collapse: collapse; }
.markdown th, .markdown td {
  border: 1px solid var(--line);
  padding: var(--space-1) var(--space-3);
  text-align: left;
}
```

- [x] **Step 3: Update `main.tsx` imports**

Replace `import "./index.css";` with:

```tsx
import "./styles/tokens.css";
import "./styles/global.css";
```

- [x] **Step 4: Delete `src/index.css`**

```bash
git rm frontend/src/index.css
```

- [x] **Step 5: Verify build + existing tests**

Run: `cd frontend && npm run type-check && npm test && npm run build`
Expected: type-check clean, all existing tests PASS (the `.markdown` selectors are unchanged), build succeeds.

- [x] **Step 6: Commit**

```bash
git add frontend/src/styles frontend/src/main.tsx
git commit -m "feat(ui): add Direction C design tokens + global stylesheet (issue #11)"
```

---

### Task 2: Button primitive + `ui/` scaffold

First component. Establishes `frontend/src/ui/` and the barrel. Semantics via `data-*` + `aria-busy` so tests work under `css: false`.

**Files:**
- Create: `frontend/src/ui/Button.tsx`, `frontend/src/ui/Button.module.css`
- Create: `frontend/src/ui/index.ts`
- Test: `frontend/src/ui/Button.test.tsx`

**Interfaces:**
- Produces: `Button` — `interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> { variant?: "primary" | "ghost"; size?: "sm" | "md"; loading?: boolean }`. Renders a `<button data-variant data-size aria-busy={loading} disabled={disabled || loading}>`; when `loading`, a `<span aria-hidden="true">` spinner precedes children.
- Produces: `ui/index.ts` re-exports every primitive as a named export.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { Button } from "./index";

test("renders children and fires onClick when enabled", async () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Send</Button>);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(onClick).toHaveBeenCalledOnce();
});

test("loading disables the button, marks it busy, and suppresses clicks", async () => {
  const onClick = vi.fn();
  render(<Button loading onClick={onClick}>Send</Button>);
  const btn = screen.getByRole("button", { name: "Send" });
  expect(btn).toBeDisabled();
  expect(btn).toHaveAttribute("aria-busy", "true");
  await userEvent.click(btn);
  expect(onClick).not.toHaveBeenCalled();
});

test("exposes variant and size as data attributes", () => {
  render(<Button variant="ghost" size="sm">X</Button>);
  const btn = screen.getByRole("button", { name: "X" });
  expect(btn).toHaveAttribute("data-variant", "ghost");
  expect(btn).toHaveAttribute("data-size", "sm");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/ui/Button.test.tsx`
Expected: FAIL — cannot resolve `./index` / `Button`.

- [x] **Step 3: Write `Button.module.css`**

```css
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
  font-family: var(--font-sans); font-weight: var(--weight-semibold);
  border: 1px solid transparent; border-radius: var(--radius-md); cursor: pointer;
  transition: background 120ms ease, opacity 120ms ease;
}
.btn[data-size="sm"] { font-size: var(--text-sm); padding: var(--space-2) var(--space-3); }
.btn[data-size="md"] { font-size: var(--text-base); padding: var(--space-3) var(--space-4); }
.btn[data-variant="primary"] { background: var(--accent); color: var(--accent-ink); }
.btn[data-variant="ghost"] { background: transparent; color: var(--accent-text); border-color: var(--line); }
.btn:disabled { opacity: 0.55; cursor: default; }
.spinner {
  width: 13px; height: 13px; border-radius: 50%;
  border: 2px solid currentColor; border-top-color: transparent;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
```

- [x] **Step 4: Write `Button.tsx`**

```tsx
import type { ButtonHTMLAttributes } from "react";
import styles from "./Button.module.css";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={styles.btn}
      data-variant={variant}
      data-size={size}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <span className={styles.spinner} aria-hidden="true" />}
      {children}
    </button>
  );
}
```

- [x] **Step 5: Write `ui/index.ts`**

```ts
export { Button } from "./Button";
export type { ButtonProps } from "./Button";
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ui/Button.test.tsx`
Expected: PASS (3 tests).

- [x] **Step 7: Commit**

```bash
git add frontend/src/ui/Button.tsx frontend/src/ui/Button.module.css frontend/src/ui/index.ts frontend/src/ui/Button.test.tsx
git commit -m "feat(ui): add Button primitive + ui/ barrel (issue #11)"
```

---

### Task 3: Input & Textarea primitives

Ref-forwarding form controls. `Textarea` autosizes; behavior tests stay in jsdom-friendly territory (rendering + change), not pixel heights.

**Files:**
- Create: `frontend/src/ui/Input.tsx`, `frontend/src/ui/Input.module.css`
- Create: `frontend/src/ui/Textarea.tsx`, `frontend/src/ui/Textarea.module.css`
- Modify: `frontend/src/ui/index.ts`
- Test: `frontend/src/ui/Input.test.tsx`

**Interfaces:**
- Consumes: nothing from prior tasks besides tokens.
- Produces: `Input` = `React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>`. `Textarea` = `React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>` that grows to fit content on input.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { Input, Textarea } from "./index";

test("Input forwards value/onChange and its ref", async () => {
  const onChange = vi.fn();
  const ref = { current: null as HTMLInputElement | null };
  render(<Input aria-label="name" ref={ref} onChange={onChange} />);
  const el = screen.getByLabelText("name");
  await userEvent.type(el, "hi");
  expect(onChange).toHaveBeenCalled();
  expect(ref.current).toBe(el);
});

test("Textarea renders with its accessible label", () => {
  render(<Textarea aria-label="Question" />);
  expect(screen.getByLabelText("Question")).toBeInTheDocument();
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/ui/Input.test.tsx`
Expected: FAIL — `Input` / `Textarea` not exported.

- [x] **Step 3: Write `Input.module.css` and `Textarea.module.css`**

`Input.module.css`:
```css
.input {
  width: 100%; box-sizing: border-box; font-family: var(--font-sans); font-size: var(--text-base);
  color: var(--ink); background: var(--bg); border: 1px solid var(--line);
  border-radius: var(--radius-md); padding: var(--space-2) var(--space-3);
}
.input::placeholder { color: var(--muted); }
```

`Textarea.module.css`:
```css
.textarea {
  width: 100%; box-sizing: border-box; font-family: var(--font-sans); font-size: var(--text-base);
  color: var(--ink); background: var(--bg); border: 1px solid var(--line);
  border-radius: var(--radius-md); padding: var(--space-2) var(--space-3);
  resize: none; min-height: 2.5rem; line-height: 1.5;
}
.textarea::placeholder { color: var(--muted); }
```

- [x] **Step 4: Write `Input.tsx` and `Textarea.tsx`**

`Input.tsx`:
```tsx
import { forwardRef, type InputHTMLAttributes } from "react";
import styles from "./Input.module.css";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input(props, ref) {
    return <input ref={ref} className={styles.input} {...props} />;
  },
);
```

`Textarea.tsx`:
```tsx
import { forwardRef, useCallback, type TextareaHTMLAttributes } from "react";
import styles from "./Textarea.module.css";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ onInput, ...props }, ref) {
    const autosize = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        const el = e.currentTarget;
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
        onInput?.(e);
      },
      [onInput],
    );
    return <textarea ref={ref} className={styles.textarea} onInput={autosize} {...props} />;
  },
);
```

- [x] **Step 5: Extend `ui/index.ts`**

```ts
export { Input } from "./Input";
export { Textarea } from "./Textarea";
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ui/Input.test.tsx`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add frontend/src/ui/Input.tsx frontend/src/ui/Input.module.css frontend/src/ui/Textarea.tsx frontend/src/ui/Textarea.module.css frontend/src/ui/index.ts frontend/src/ui/Input.test.tsx
git commit -m "feat(ui): add Input and autosizing Textarea primitives (issue #11)"
```

---

### Task 4: Card & Badge primitives

Two presentational containers. `Badge` carries `data-tone` for testable semantics; `DatasetChips` adopts it in Task 11.

**Files:**
- Create: `frontend/src/ui/Card.tsx`, `frontend/src/ui/Card.module.css`
- Create: `frontend/src/ui/Badge.tsx`, `frontend/src/ui/Badge.module.css`
- Modify: `frontend/src/ui/index.ts`
- Test: `frontend/src/ui/Card.test.tsx`

**Interfaces:**
- Produces: `Card` — `interface CardProps extends React.HTMLAttributes<HTMLDivElement> {}`; renders a `<div>` surface with children. `Badge` — `interface BadgeProps { tone?: "neutral" | "accent" | "danger"; children: React.ReactNode }`; renders `<span data-tone>`.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { Card, Badge } from "./index";

test("Card renders its children", () => {
  render(<Card>inside</Card>);
  expect(screen.getByText("inside")).toBeInTheDocument();
});

test("Badge renders children and exposes its tone", () => {
  render(<Badge tone="accent">hist</Badge>);
  const el = screen.getByText("hist");
  expect(el).toHaveAttribute("data-tone", "accent");
});

test("Badge defaults to the neutral tone", () => {
  render(<Badge>x</Badge>);
  expect(screen.getByText("x")).toHaveAttribute("data-tone", "neutral");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/ui/Card.test.tsx`
Expected: FAIL — `Card` / `Badge` not exported.

- [x] **Step 3: Write the CSS modules**

`Card.module.css`:
```css
.card {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius-lg); padding: var(--space-4);
}
```

`Badge.module.css`:
```css
.badge {
  display: inline-block; font-size: var(--text-xs); font-weight: var(--weight-medium);
  padding: var(--space-1) var(--space-2); border-radius: 999px; line-height: 1.4;
}
.badge[data-tone="neutral"] { background: color-mix(in srgb, var(--muted) 14%, transparent); color: var(--ink); }
.badge[data-tone="accent"] { background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent-text); }
.badge[data-tone="danger"] { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
```

- [x] **Step 4: Write `Card.tsx` and `Badge.tsx`**

`Card.tsx`:
```tsx
import type { HTMLAttributes } from "react";
import styles from "./Card.module.css";

export function Card({ children, className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={className ? `${styles.card} ${className}` : styles.card} {...rest}>
      {children}
    </div>
  );
}
```

`Badge.tsx`:
```tsx
import type { ReactNode } from "react";
import styles from "./Badge.module.css";

export interface BadgeProps {
  tone?: "neutral" | "accent" | "danger";
  children: ReactNode;
}

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span className={styles.badge} data-tone={tone}>
      {children}
    </span>
  );
}
```

- [x] **Step 5: Extend `ui/index.ts`**

```ts
export { Card } from "./Card";
export { Badge } from "./Badge";
export type { BadgeProps } from "./Badge";
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ui/Card.test.tsx`
Expected: PASS (3 tests).

- [x] **Step 7: Commit**

```bash
git add frontend/src/ui/Card.tsx frontend/src/ui/Card.module.css frontend/src/ui/Badge.tsx frontend/src/ui/Badge.module.css frontend/src/ui/index.ts frontend/src/ui/Card.test.tsx
git commit -m "feat(ui): add Card and Badge primitives (issue #11)"
```

---

### Task 5: Dialog primitive (Radix) + jsdom test shims

Adds the sole new dependency and the accessible modal shipped now for Slice C to reuse. Radix + jsdom need a few no-op globals; add them to `setupTests.ts` so this and later interactive tests are stable.

**Files:**
- Modify: `frontend/package.json` (add `@radix-ui/react-dialog`)
- Modify: `frontend/src/setupTests.ts` (jsdom shims)
- Create: `frontend/src/ui/Dialog.tsx`, `frontend/src/ui/Dialog.module.css`
- Modify: `frontend/src/ui/index.ts`
- Test: `frontend/src/ui/Dialog.test.tsx`

**Interfaces:**
- Produces: `Dialog` — `interface DialogProps { trigger: React.ReactNode; title: string; children: React.ReactNode; open?: boolean; onOpenChange?: (open: boolean) => void }`. Renders a Radix modal with an accessible (visually-hidden-capable) title and a labelled close button.

- [x] **Step 1: Install the dependency**

Run: `cd frontend && npm install @radix-ui/react-dialog`
Expected: `@radix-ui/react-dialog` appears under `dependencies` in `package.json`; `package-lock.json` updates.

- [x] **Step 2: Add jsdom shims to `setupTests.ts`**

Append below the existing `import "@testing-library/jest-dom";`:

```ts
// jsdom lacks these; Radix + the ThemeProvider rely on them in tests.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
if (!("ResizeObserver" in window)) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
```

- [x] **Step 3: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "./index";

function open() {
  return userEvent.click(screen.getByRole("button", { name: "Expand" }));
}

test("Dialog is closed until the trigger is clicked", async () => {
  render(
    <Dialog trigger={<button>Expand</button>} title="Chart detail">
      <p>body</p>
    </Dialog>,
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await open();
  expect(screen.getByRole("dialog", { name: "Chart detail" })).toBeInTheDocument();
});

test("Dialog closes on Escape", async () => {
  render(
    <Dialog trigger={<button>Expand</button>} title="Chart detail">
      <p>body</p>
    </Dialog>,
  );
  await open();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
```

- [x] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/ui/Dialog.test.tsx`
Expected: FAIL — `Dialog` not exported.

- [x] **Step 5: Write `Dialog.module.css`**

```css
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); }
.content {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  max-width: min(90vw, 900px); max-height: 85vh; overflow: auto;
  background: var(--surface); color: var(--ink);
  border: 1px solid var(--line); border-radius: var(--radius-lg); padding: var(--space-4);
}
.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-3); }
.title { margin: 0; font-size: var(--text-lg); font-weight: var(--weight-semibold); }
.close {
  border: none; background: transparent; color: var(--muted);
  font-size: var(--text-lg); cursor: pointer; border-radius: var(--radius-sm); padding: 0 var(--space-2);
}
```

- [x] **Step 6: Write `Dialog.tsx`**

```tsx
import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import styles from "./Dialog.module.css";

export interface DialogProps {
  trigger: ReactNode;
  title: string;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function Dialog({ trigger, title, children, open, onOpenChange }: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.overlay} />
        <RadixDialog.Content className={styles.content}>
          <div className={styles.header}>
            <RadixDialog.Title className={styles.title}>{title}</RadixDialog.Title>
            <RadixDialog.Close aria-label="Close" className={styles.close}>×</RadixDialog.Close>
          </div>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
```

- [x] **Step 7: Extend `ui/index.ts`**

```ts
export { Dialog } from "./Dialog";
export type { DialogProps } from "./Dialog";
```

- [x] **Step 8: Run tests + full suite**

Run: `cd frontend && npx vitest run src/ui/Dialog.test.tsx && npm test && npm run type-check`
Expected: Dialog tests PASS; the full suite stays green with the new shims.

- [x] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/setupTests.ts frontend/src/ui/Dialog.tsx frontend/src/ui/Dialog.module.css frontend/src/ui/index.ts frontend/src/ui/Dialog.test.tsx
git commit -m "feat(ui): add accessible Dialog (Radix) + jsdom test shims (issue #11)"
```

---

### Task 6: Skeleton & IconButton primitives

Loading placeholder (decorative, `aria-hidden`) and a label-required icon button (the pattern Slice C's copy/download buttons follow).

**Files:**
- Create: `frontend/src/ui/Skeleton.tsx`, `frontend/src/ui/Skeleton.module.css`
- Create: `frontend/src/ui/IconButton.tsx`, `frontend/src/ui/IconButton.module.css`
- Modify: `frontend/src/ui/index.ts`
- Test: `frontend/src/ui/Skeleton.test.tsx`, `frontend/src/ui/IconButton.test.tsx`

**Interfaces:**
- Produces: `Skeleton` — `interface SkeletonProps { variant?: "line" | "block"; count?: number }`; renders `count` `aria-hidden` placeholders with `data-variant`, wrapped in a `role="status"` container whose accessible name is "Loading". `IconButton` — `interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> { label: string }`; renders `<button aria-label={label}>` with `aria-hidden` icon children.

- [x] **Step 1: Write the failing tests**

`Skeleton.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { Skeleton } from "./index";

test("renders a labelled status region with the requested number of placeholders", () => {
  render(<Skeleton count={3} />);
  const status = screen.getByRole("status", { name: "Loading" });
  expect(status.querySelectorAll("[data-variant]")).toHaveLength(3);
});

test("defaults to a single line placeholder", () => {
  render(<Skeleton />);
  const status = screen.getByRole("status");
  const items = status.querySelectorAll("[data-variant]");
  expect(items).toHaveLength(1);
  expect(items[0]).toHaveAttribute("data-variant", "line");
});
```

`IconButton.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { IconButton } from "./index";

test("exposes its label as the accessible name and fires onClick", async () => {
  const onClick = vi.fn();
  render(<IconButton label="Copy answer" onClick={onClick}><svg /></IconButton>);
  const btn = screen.getByRole("button", { name: "Copy answer" });
  await userEvent.click(btn);
  expect(onClick).toHaveBeenCalledOnce();
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/ui/Skeleton.test.tsx src/ui/IconButton.test.tsx`
Expected: FAIL — components not exported.

- [x] **Step 3: Write the CSS modules**

`Skeleton.module.css`:
```css
.wrap { display: flex; flex-direction: column; gap: var(--space-2); }
.item {
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--muted) 12%, transparent),
    color-mix(in srgb, var(--muted) 22%, transparent),
    color-mix(in srgb, var(--muted) 12%, transparent));
  background-size: 200% 100%; border-radius: var(--radius-sm);
  animation: shimmer 1.4s ease-in-out infinite;
}
.item[data-variant="line"] { height: 0.9rem; width: 100%; }
.item[data-variant="block"] { height: 120px; width: 100%; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .item { animation: none; } }
```

`IconButton.module.css`:
```css
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border: 1px solid transparent; border-radius: var(--radius-md);
  background: transparent; color: var(--muted); cursor: pointer;
}
.btn:hover { background: color-mix(in srgb, var(--muted) 12%, transparent); color: var(--ink); }
.btn:disabled { opacity: 0.5; cursor: default; }
```

- [x] **Step 4: Write the components**

`Skeleton.tsx`:
```tsx
import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  variant?: "line" | "block";
  count?: number;
}

export function Skeleton({ variant = "line", count = 1 }: SkeletonProps) {
  return (
    <div className={styles.wrap} role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className={styles.item} data-variant={variant} aria-hidden="true" />
      ))}
    </div>
  );
}
```

`IconButton.tsx`:
```tsx
import type { ButtonHTMLAttributes } from "react";
import styles from "./IconButton.module.css";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
}

export function IconButton({ label, children, ...rest }: IconButtonProps) {
  return (
    <button type="button" aria-label={label} className={styles.btn} {...rest}>
      <span aria-hidden="true">{children}</span>
    </button>
  );
}
```

- [x] **Step 5: Extend `ui/index.ts`**

```ts
export { Skeleton } from "./Skeleton";
export type { SkeletonProps } from "./Skeleton";
export { IconButton } from "./IconButton";
export type { IconButtonProps } from "./IconButton";
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ui/Skeleton.test.tsx src/ui/IconButton.test.tsx`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add frontend/src/ui/Skeleton.tsx frontend/src/ui/Skeleton.module.css frontend/src/ui/IconButton.tsx frontend/src/ui/IconButton.module.css frontend/src/ui/index.ts frontend/src/ui/Skeleton.test.tsx frontend/src/ui/IconButton.test.tsx
git commit -m "feat(ui): add Skeleton and IconButton primitives (issue #11)"
```

---

### Task 7: Theme provider, ThemeToggle & app wiring

Dark mode. `ThemeProvider` resolves the initial theme (stored value → OS preference), applies `data-theme` to `<html>`, and exposes a toggle. `ThemeToggle` uses `IconButton`. Wire the provider at the root.

**Files:**
- Create: `frontend/src/theme.tsx`
- Create: `frontend/src/ui/ThemeToggle.tsx`
- Modify: `frontend/src/ui/index.ts`
- Modify: `frontend/src/main.tsx` (wrap `<App/>` in `<ThemeProvider>`)
- Test: `frontend/src/theme.test.tsx`

**Interfaces:**
- Consumes: `IconButton` (Task 6). Relies on the `matchMedia` shim (Task 5).
- Produces: `ThemeProvider` (`{ children }`), `useTheme()` → `{ theme: "light" | "dark"; toggle: () => void; setTheme: (t) => void }`, `ThemeToggle` (no props). Storage key: `"wp-theme"`.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach } from "vitest";
import { ThemeProvider, useTheme } from "./theme";
import { ThemeToggle } from "./ui";

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="theme">{theme}</span>;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

test("uses the stored theme and applies it to <html>", () => {
  localStorage.setItem("wp-theme", "dark");
  render(<ThemeProvider><Probe /></ThemeProvider>);
  expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});

test("defaults to light when nothing is stored (matchMedia stub returns no-preference)", () => {
  render(<ThemeProvider><Probe /></ThemeProvider>);
  expect(screen.getByTestId("theme")).toHaveTextContent("light");
});

test("ThemeToggle flips the theme and persists it", async () => {
  render(<ThemeProvider><Probe /><ThemeToggle /></ThemeProvider>);
  await userEvent.click(screen.getByRole("button", { name: /theme/i }));
  expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  expect(localStorage.getItem("wp-theme")).toBe("dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/theme.test.tsx`
Expected: FAIL — `theme` module / `ThemeToggle` missing.

- [x] **Step 3: Write `theme.tsx`**

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "light" | "dark";
const STORAGE_KEY = "wp-theme";

interface ThemeContextValue {
  theme: Theme;
  toggle: () => void;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function resolveInitial(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(resolveInitial);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value: ThemeContextValue = {
    theme,
    setTheme: setThemeState,
    toggle: () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
  };
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
```

- [x] **Step 4: Write `ui/ThemeToggle.tsx`**

```tsx
import { IconButton } from "./IconButton";
import { useTheme } from "../theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <IconButton
      label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      onClick={toggle}
    >
      {theme === "dark" ? "🌙" : "🌞"}
    </IconButton>
  );
}
```

- [x] **Step 5: Extend `ui/index.ts` and wrap the app**

Add to `ui/index.ts`:
```ts
export { ThemeToggle } from "./ThemeToggle";
```

In `main.tsx`, import and wrap:
```tsx
import { ThemeProvider } from "./theme";
// …
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
```

- [x] **Step 6: Run tests + full suite**

Run: `cd frontend && npx vitest run src/theme.test.tsx && npm test && npm run type-check`
Expected: theme tests PASS; full suite green.

- [x] **Step 7: Commit**

```bash
git add frontend/src/theme.tsx frontend/src/theme.test.tsx frontend/src/ui/ThemeToggle.tsx frontend/src/ui/index.ts frontend/src/main.tsx
git commit -m "feat(ui): add ThemeProvider + dark-mode toggle (issue #11)"
```

---

### Task 8: AppShell

The frame both routes render inside: sticky topbar (brand + optional right slot + ThemeToggle) and a width-constrained content region.

**Files:**
- Create: `frontend/src/components/AppShell.tsx`, `frontend/src/components/AppShell.module.css`
- Test: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: `ThemeToggle` (Task 7). Must render under a `ThemeProvider` (tests wrap it).
- Produces: `AppShell` — `interface AppShellProps { children: React.ReactNode; topbarRight?: React.ReactNode; width?: "chat" | "upload" }`. Renders one `<header>` (brand "CSV Analysis" + `topbarRight` + ThemeToggle) and one `<main data-width>` containing `children`.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "../theme";
import AppShell from "./AppShell";

function renderShell(ui: React.ReactNode, right?: React.ReactNode) {
  render(
    <ThemeProvider>
      <AppShell topbarRight={right}>{ui}</AppShell>
    </ThemeProvider>,
  );
}

test("renders the brand, the theme toggle, a right slot, and its children", () => {
  renderShell(<p>page body</p>, <span>chips</span>);
  expect(screen.getByText("CSV Analysis")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  expect(screen.getByText("chips")).toBeInTheDocument();
  expect(screen.getByText("page body")).toBeInTheDocument();
});

test("exposes the width variant on its main region", () => {
  render(
    <ThemeProvider>
      <AppShell width="upload">x</AppShell>
    </ThemeProvider>,
  );
  expect(screen.getByRole("main")).toHaveAttribute("data-width", "upload");
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AppShell.test.tsx`
Expected: FAIL — `AppShell` missing.

- [x] **Step 3: Write `AppShell.module.css`**

```css
.shell { min-height: 100vh; background: var(--bg); }
.topbar {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface); border-bottom: 1px solid var(--line);
}
.brand { font-size: var(--text-lg); font-weight: var(--weight-bold); color: var(--ink); letter-spacing: -0.01em; }
.right { display: flex; align-items: center; gap: var(--space-3); }
.main { margin: 0 auto; padding: var(--space-6) var(--space-4); }
.main[data-width="chat"] { max-width: 820px; }
.main[data-width="upload"] { max-width: 520px; }
```

- [x] **Step 4: Write `AppShell.tsx`**

```tsx
import type { ReactNode } from "react";
import { ThemeToggle } from "../ui";
import styles from "./AppShell.module.css";

interface AppShellProps {
  children: ReactNode;
  topbarRight?: ReactNode;
  width?: "chat" | "upload";
}

export default function AppShell({ children, topbarRight, width = "chat" }: AppShellProps) {
  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <span className={styles.brand}>CSV Analysis</span>
        <div className={styles.right}>
          {topbarRight}
          <ThemeToggle />
        </div>
      </header>
      <main data-width={width} className={styles.main}>
        {children}
      </main>
    </div>
  );
}
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/AppShell.test.tsx`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/AppShell.module.css frontend/src/components/AppShell.test.tsx
git commit -m "feat(ui): add AppShell frame (issue #11)"
```

---

### Task 9: Restyle UploadPage

Wrap the page in `AppShell` (upload width) + a `Card` hero, swap the raw file input/button for a friendlier layout using `Button`. Preserve every existing test hook: `aria-label="CSV files"`, button name `"Upload"`/`"Uploading…"`, `role="alert"`.

**Files:**
- Modify: `frontend/src/pages/UploadPage.tsx`
- Create: `frontend/src/pages/UploadPage.module.css`
- Test: `frontend/src/pages/UploadPage.test.tsx` (existing tests must still pass; add one)

**Interfaces:**
- Consumes: `AppShell` (Task 8), `Button`, `Card` (Tasks 2, 4). Runs under the root `ThemeProvider`; existing tests wrap in `MemoryRouter` only — the shell's `ThemeToggle` needs a provider, so the test render must add `ThemeProvider`.

- [x] **Step 1: Add the ThemeProvider wrapper + a hero test to `UploadPage.test.tsx`**

Update `renderPage()` to include the provider (the shell renders a ThemeToggle):
```tsx
import { ThemeProvider } from "../theme";
// …
function renderPage() {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <UploadPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}
```
Add:
```tsx
test("shows the upload hero heading", () => {
  renderPage();
  expect(screen.getByRole("heading", { name: /CSV Analysis Assistant/i })).toBeInTheDocument();
});
```

- [x] **Step 2: Run tests to verify the new one fails / others still pass structurally**

Run: `cd frontend && npx vitest run src/pages/UploadPage.test.tsx`
Expected: the heading test PASSES already (heading text is unchanged), existing tests PASS. If any existing test now fails because the shell changed roles, note it — it should not, since selectors are preserved. (This step confirms the provider wrapper didn't break anything before the visual rewrite.)

- [x] **Step 3: Write `UploadPage.module.css`**

```css
.hero { display: flex; flex-direction: column; gap: var(--space-3); text-align: center; }
.hero h1 { margin: 0; font-size: var(--text-2xl); color: var(--ink); }
.hero p { margin: 0; color: var(--muted); font-size: var(--text-base); }
.form { display: flex; flex-direction: column; gap: var(--space-4); margin-top: var(--space-2); align-items: center; }
.file { font-size: var(--text-sm); color: var(--ink); }
```

- [x] **Step 4: Rewrite `UploadPage.tsx` render (logic unchanged)**

Keep all existing state/handlers exactly. Replace only the returned JSX:
```tsx
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createChat, uploadDataset } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import AppShell from "../components/AppShell";
import { Button, Card } from "../ui";
import styles from "./UploadPage.module.css";

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(e.target.files ?? []));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (files.length === 0 || pending) return;
    setPending(true);
    setError(null);
    try {
      const datasetIds: string[] = [];
      for (const file of files) {
        const dataset = await uploadDataset(file);
        datasetIds.push(dataset.id);
      }
      const chat = await createChat(datasetIds);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setPending(false);
    }
  }

  return (
    <AppShell width="upload">
      <Card>
        <div className={styles.hero}>
          <h1>CSV Analysis Assistant</h1>
          <p>Upload one or more CSVs to start asking questions about them.</p>
        </div>
        <form className={styles.form} onSubmit={handleSubmit}>
          <input
            className={styles.file}
            type="file"
            accept=".csv"
            multiple
            aria-label="CSV files"
            onChange={handleFileChange}
          />
          <Button type="submit" disabled={files.length === 0} loading={pending}>
            {pending ? "Uploading…" : "Upload"}
          </Button>
        </form>
        {error && <ErrorBanner message={error} />}
      </Card>
    </AppShell>
  );
}
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/UploadPage.test.tsx && npm run type-check`
Expected: all UploadPage tests PASS. (Button with `loading={pending}` stays disabled+busy during upload; name remains "Uploading…" so the `name: "Upload"` query still matches the accessible name before submit.)

- [x] **Step 6: Commit**

```bash
git add frontend/src/pages/UploadPage.tsx frontend/src/pages/UploadPage.module.css frontend/src/pages/UploadPage.test.tsx
git commit -m "feat(ui): restyle UploadPage onto AppShell + Card + Button (issue #11)"
```

---

### Task 10: Restyle ChatPage — shell, skeleton loading, empty state

Wrap Chat in `AppShell` with `DatasetChips` in the topbar-right slot, replace the bare `"Loading…"` with a `Skeleton`, and give the no-messages case a proper empty state. Preserve the `MemoryRouter`/`useParams` test setup and existing behavior.

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Create: `frontend/src/pages/ChatPage.module.css`
- Test: `frontend/src/pages/ChatPage.test.tsx` (existing tests must still pass; add loading + empty-state assertions)

**Interfaces:**
- Consumes: `AppShell` (Task 8), `Skeleton` (Task 6), `DatasetChips` (unchanged here; restyled in Task 11). Tests must wrap in `ThemeProvider` (shell renders ThemeToggle).

- [x] **Step 1: Update the existing test's `renderAt` helper and add the new cases**

The suite renders ChatPage through a local `renderAt(chatId)` helper that mounts it under a `MemoryRouter`/`Routes`/`Route` so `useParams` resolves `:chatId`. Wrap that helper's tree in `<ThemeProvider>` (the shell renders `ThemeToggle`, which calls `useTheme`). Change the helper in place:
```tsx
import { ThemeProvider } from "../theme";

function renderAt(chatId: string) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[`/c/${chatId}`]}>
        <Routes>
          <Route path="/c/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}
```
Then append the two new behavior tests. Match the suite's existing mock idiom — it spies on `getChatHistory` from `../api` and resolves the history shape `{ datasets, messages }`:
```tsx
test("shows a loading skeleton before history resolves", () => {
  // history fetch pending: getChatHistory returns a never-resolving promise
  vi.spyOn(api, "getChatHistory").mockReturnValue(new Promise(() => {}));
  renderAt("c1");
  expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
});

test("shows an empty state when there are no messages", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "d1", name: "d.csv" }],
    messages: [],
  });
  renderAt("c1");
  expect(await screen.findByText(/Ask your first question/i)).toBeInTheDocument();
});
```

- [x] **Step 2: Run tests to verify the new ones fail**

Run: `cd frontend && npx vitest run src/pages/ChatPage.test.tsx`
Expected: the skeleton test FAILS (current loading state is a `<p>Loading…</p>`, no `role="status"`).

- [x] **Step 3: Write `ChatPage.module.css`**

```css
.messages { display: flex; flex-direction: column; gap: var(--space-4); margin-bottom: var(--space-6); }
.empty { color: var(--muted); font-size: var(--text-base); text-align: center; padding: var(--space-8) 0; }
.loading { padding: var(--space-4) 0; }
```

- [x] **Step 4: Rewrite `ChatPage.tsx` render (data/handlers unchanged)**

Keep all existing state, `useEffect`, and `handleAsk` exactly. Replace only the returned JSX and the loading branch:
```tsx
import AppShell from "../components/AppShell";
import DatasetChips from "../components/DatasetChips";
import { Skeleton } from "../ui";
import styles from "./ChatPage.module.css";
// … existing imports (ChatTurn, QuestionBox, ErrorBanner, hooks, api, types) unchanged …

  if (loading) {
    return (
      <AppShell>
        <div className={styles.loading}>
          <Skeleton variant="block" />
          <Skeleton count={2} />
        </div>
      </AppShell>
    );
  }
  if (loadError) {
    return (
      <AppShell>
        <ErrorBanner message={loadError} />
      </AppShell>
    );
  }

  return (
    <AppShell topbarRight={<DatasetChips datasets={datasets} />}>
      {messages.length === 0 && (
        <p className={styles.empty}>Ask your first question about these datasets.</p>
      )}
      <div className={styles.messages}>
        {messages.map((m) => (
          <ChatTurn key={m.id} message={m} />
        ))}
      </div>
      {askError && <ErrorBanner message={askError} />}
      <QuestionBox onSubmit={handleAsk} pending={pending} />
    </AppShell>
  );
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/ChatPage.test.tsx && npm run type-check`
Expected: all ChatPage tests PASS, including the new skeleton + empty-state cases.

- [x] **Step 6: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/src/pages/ChatPage.module.css frontend/src/pages/ChatPage.test.tsx
git commit -m "feat(ui): restyle ChatPage with AppShell, skeleton loading + empty state (issue #11)"
```

---

### Task 11: Restyle leaf components onto tokens / `ui/`

Adopt the primitives in the remaining components. Behavior and all existing test hooks are preserved; only styling/markup wrappers change.

**Files:**
- Modify: `frontend/src/components/QuestionBox.tsx` (use `Textarea` + `Button`)
- Modify: `frontend/src/components/DatasetChips.tsx` (use `Badge`)
- Modify: `frontend/src/components/StatsDetails.tsx` + create `StatsDetails.module.css` (token styling)
- Modify: `frontend/src/components/ChartList.tsx` + create `ChartList.module.css` (spacing tokens)
- Modify: `frontend/src/components/ChatTurn.tsx` + create `ChatTurn.module.css` (role label + layout)
- Modify: `frontend/src/components/ErrorBanner.module.css` (retint onto `--danger` tokens)
- Test: existing component tests must stay green; add a Badge-adoption assertion to `DatasetChips.test.tsx`

**Interfaces:**
- Consumes: `Textarea`, `Button`, `Badge` (Tasks 2–4). No signature changes to any component's props.

- [x] **Step 1: Update `DatasetChips.test.tsx` to assert Badge adoption (keep the existing list-label test)**

```tsx
test("renders each dataset name as a badge", () => {
  render(<DatasetChips datasets={[{ id: "d1", name: "a.csv" }]} />);
  const chip = screen.getByText("a.csv");
  expect(chip).toHaveAttribute("data-tone"); // Badge sets data-tone
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/DatasetChips.test.tsx`
Expected: FAIL — current `<li>` has no `data-tone`.

- [x] **Step 3: Restyle `QuestionBox.tsx`** (preserve `aria-label="Question"`, button name `"Ask"`/`"Asking…"`, submit-on-button-only behavior)

```tsx
import { useState, type FormEvent } from "react";
import { Button, Textarea } from "../ui";
import styles from "./QuestionBox.module.css";

interface Props {
  onSubmit: (question: string) => void;
  pending: boolean;
}

export default function QuestionBox({ onSubmit, pending }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || pending) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <Textarea
        aria-label="Question"
        placeholder="Ask a question about your data…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={pending}
      />
      <Button type="submit" disabled={value.trim() === ""} loading={pending}>
        {pending ? "Asking…" : "Ask"}
      </Button>
    </form>
  );
}
```

Create `QuestionBox.module.css`:
```css
.form { display: flex; flex-direction: column; gap: var(--space-3); align-items: flex-end; }
.form > :first-child { width: 100%; }
```

- [x] **Step 4: Restyle `DatasetChips.tsx`** (preserve `aria-label="Attached datasets"`)

```tsx
import type { ChatDatasetOut } from "../types";
import { Badge } from "../ui";
import styles from "./DatasetChips.module.css";

interface Props {
  datasets: ChatDatasetOut[];
}

export default function DatasetChips({ datasets }: Props) {
  if (datasets.length === 0) return null;
  return (
    <ul className={styles.list} aria-label="Attached datasets">
      {datasets.map((d) => (
        <li key={d.id}>
          <Badge tone="accent">{d.name}</Badge>
        </li>
      ))}
    </ul>
  );
}
```

Create `DatasetChips.module.css`:
```css
.list { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
```

- [x] **Step 5: Restyle `StatsDetails.tsx`, `ChartList.tsx`, `ChatTurn.tsx`, `ErrorBanner.module.css`**

`StatsDetails.module.css`:
```css
.details { margin-top: var(--space-3); }
.summary { cursor: pointer; color: var(--accent-text); font-size: var(--text-sm); }
.pre {
  background: color-mix(in srgb, var(--muted) 12%, transparent);
  border-radius: var(--radius-md); padding: var(--space-3); overflow-x: auto; font-size: var(--text-xs);
}
```
`StatsDetails.tsx` (preserve `<summary>"Raw statistics"`):
```tsx
import styles from "./StatsDetails.module.css";

interface Props {
  stats: Record<string, unknown>[];
}

export default function StatsDetails({ stats }: Props) {
  if (stats.length === 0) return null;
  return (
    <details className={styles.details}>
      <summary className={styles.summary}>Raw statistics</summary>
      <pre className={styles.pre}>{JSON.stringify(stats, null, 2)}</pre>
    </details>
  );
}
```

`ChartList.module.css`:
```css
.list { display: flex; flex-direction: column; gap: var(--space-3); margin: var(--space-3) 0; }
.list img { border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface); }
```
`ChartList.tsx` (preserve `alt="chart N"`):
```tsx
import styles from "./ChartList.module.css";

interface Props {
  charts: string[];
}

export default function ChartList({ charts }: Props) {
  if (charts.length === 0) return null;
  return (
    <div className={styles.list}>
      {charts.map((c, i) => (
        <img key={i} src={`data:image/png;base64,${c}`} alt={`chart ${i + 1}`} />
      ))}
    </div>
  );
}
```

`ChatTurn.module.css`:
```css
.turn { display: flex; flex-direction: column; gap: var(--space-2); }
.turn[data-role="assistant"] {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius-lg); padding: var(--space-4);
}
.role { font-size: var(--text-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
```
`ChatTurn.tsx` — keep the Markdown branch (Global Constraint) and all children; wrap for layout:
```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessageOut } from "../types";
import ChartList from "./ChartList";
import StatsDetails from "./StatsDetails";
import ErrorBanner from "./ErrorBanner";
import styles from "./ChatTurn.module.css";

interface Props {
  message: ChatMessageOut;
}

export default function ChatTurn({ message }: Props) {
  return (
    <div className={styles.turn} data-role={message.role}>
      <span className={styles.role}>{message.role}</span>
      {message.content &&
        (message.role === "assistant" ? (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ) : (
          <p>{message.content}</p>
        ))}
      <ChartList charts={message.charts} />
      {message.errors.map((e, i) => (
        <ErrorBanner key={i} message={e} />
      ))}
      <StatsDetails stats={message.stats} />
    </div>
  );
}
```

`ErrorBanner.module.css` (retint onto tokens; keep `.banner` class name):
```css
.banner {
  margin: var(--space-2) 0; padding: var(--space-2) var(--space-3);
  border: 1px solid var(--danger); border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--danger) 10%, transparent); color: var(--danger);
}
```

- [x] **Step 6: Run the full frontend suite + type-check**

Run: `cd frontend && npm test && npm run type-check`
Expected: every test PASSES — existing hooks (`Question`, `Ask`, `Attached datasets`, `Raw statistics`, `chart N`, `role="alert"`) are intact; the new Badge assertion passes.

- [x] **Step 7: Commit**

```bash
git add frontend/src/components
git commit -m "feat(ui): restyle chat leaf components onto tokens + ui primitives (issue #11)"
```

---

### Task 12: Manual QA, doc sync & final gate

Verify the running app (dark mode + responsive), then sync the docs CLAUDE.md requires before a feature merges.

**Files:**
- Modify: `README.md` (feature list: dark mode + refreshed UI)
- Modify: `CLAUDE.md` (code-layout: `frontend/src/ui/`, `styles/`, `theme.tsx`, `AppShell`; note the Radix + CSS-token foundation)
- Modify: `doc/plans/2026-08-01-project-1-ui-ux-foundation.md` (tick completed task checkboxes)

- [ ] **Step 1: Manual QA against the dev server**

Run backend (`make dev`) + `cd frontend && npm run dev`. In the browser: upload a CSV, ask a question, confirm charts/stats/Markdown render; toggle dark mode and confirm it persists across reload; narrow the window to ~768px and confirm the layout holds. Note any visual defects and fix before proceeding.

- [x] **Step 2: Full gate**

Run: `cd frontend && npm test && npm run type-check && npm run build`
Expected: all green; production build succeeds.

- [x] **Step 3: Update `README.md`**

In the "Architecture at a glance" / feature area, add a line noting the app now ships a tokenized component system with light/dark themes and a refreshed Upload + Chat UI (issue #11, Slice A). No command changes.

- [x] **Step 4: Update `CLAUDE.md`**

In the frontend code-layout block, add `ui/` (primitive library), `styles/` (tokens + global), `theme.tsx` (ThemeProvider), and `components/AppShell.tsx`. Add a one-line non-obvious note: the frontend design foundation is **Radix primitives + CSS-variable tokens + CSS modules** (issue #11), and component tests assert on roles/`data-*`/text — never CSS-module class names (Vitest `css: false`).

- [x] **Step 5: Tick this plan's checkboxes and commit the doc sync**

```bash
git add README.md CLAUDE.md doc/plans/2026-08-01-project-1-ui-ux-foundation.md
git commit -m "docs: sync README/CLAUDE for the UI/UX foundation (issue #11)"
```

- [ ] **Step 6: Push the branch and open the PR**

```bash
git push -u origin feat/issue-11-ui-ux-enhancements
gh pr create --title "feat: UI/UX design foundation (issue #11, Slice A)" \
  --body "Design tokens, ui/ primitive library, dark mode, app shell, loading skeletons; restyled Upload + Chat pages. First slice of issue #11. See doc/project-1-ui-ux-foundation-design.md."
```

---

## Notes for the executor

- **Order matters:** Tasks 2–8 build the library bottom-up (primitives → theme → shell); 9–11 consume it; 12 verifies + documents. Task 7 depends on Task 6 (`IconButton`) and Task 5's `matchMedia` shim.
- **Every page-test render must be wrapped in `ThemeProvider`** once the page uses `AppShell` (the shell renders `ThemeToggle`, which calls `useTheme`). Tasks 9 and 10 update those helpers.
- **Never assert CSS-module class names** — Vitest runs with `css: false`. Use roles, accessible names, visible text, or `data-*`.
- **Do not add deferred features.** If a task tempts you toward drag-drop, timestamps, chart zoom, or a sidebar, stop — those are Slices B/C/D.
