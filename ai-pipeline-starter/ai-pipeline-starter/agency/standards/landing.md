# Agency Standard: Landing Page

**Version:** 1.0
**Last updated:** 2026-05-15

This document defines how landing pages are built in this agency. Any AI agent generating a landing page MUST follow these standards.

## Stack (LOCKED)

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Framework | Next.js | 15.x | App Router only, no Pages Router |
| Language | TypeScript | strict mode | No `any` allowed |
| Styling | Tailwind CSS | 4.x | + shadcn/ui base components |
| Forms | react-hook-form | latest | + zod for validation |
| Animation | framer-motion | latest | Sparingly |
| Icons | lucide-react | latest | No custom SVGs except logos |
| Fonts | next/font (Google Fonts) | — | Inter Tight + JetBrains Mono for code-feel |
| Deployment | Vercel | — | Edge runtime where possible |
| Analytics | Plausible | — | Only if client requests |

## Folder structure

```
project-root/
├── app/
│   ├── (marketing)/
│   │   ├── page.tsx              # landing page (one route)
│   │   └── layout.tsx            # marketing layout
│   ├── api/
│   │   └── lead/
│   │       └── route.ts          # form submissions (if needed)
│   ├── layout.tsx                # root layout
│   ├── not-found.tsx
│   └── error.tsx
├── components/
│   ├── ui/                       # shadcn components (button, input, etc.)
│   ├── sections/                 # page sections
│   │   ├── hero.tsx
│   │   ├── benefits.tsx
│   │   ├── how-it-works.tsx
│   │   ├── pricing.tsx
│   │   ├── faq.tsx
│   │   └── cta.tsx
│   ├── shared/
│   │   ├── footer.tsx
│   │   ├── header.tsx
│   │   └── telegram-button.tsx
│   └── icons/                    # only logo etc.
├── content/                      # typed content (i18n-ready)
│   ├── hero.ts
│   ├── benefits.ts
│   ├── pricing.ts
│   ├── faq.ts
│   └── seo.ts
├── lib/
│   ├── utils.ts                  # cn() helper, etc.
│   ├── telegram.ts               # Telegram CTA helper
│   └── analytics.ts              # Plausible wrapper (if used)
├── public/
│   ├── og.png                    # OG image (1200x630)
│   ├── favicon.ico
│   └── (other static assets)
├── styles/
│   └── globals.css
├── .env.example                  # placeholders only
├── next.config.mjs
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

## Conventions

### Components

- **Server components by default.** Use `"use client"` only when:
  - Component needs `useState`, `useEffect`, or other hooks
  - Component handles user interactions (forms, animations triggered by user)
  - Component uses browser-only APIs
- **One component per file.** Filename = component name in kebab-case (e.g. `hero-section.tsx` exports `HeroSection`).
- **Props always typed via interface.** Never inline anonymous types for component props.
- **No default exports for components** — named exports preferred for refactor safety.

### Styling

- **Tailwind utility-first.** No CSS modules, no styled-components, no emotion.
- **No inline styles** (`style={{...}}`) unless dynamic value can't be a Tailwind class.
- **Custom classes** only in `globals.css` under `@layer components` for repeated patterns.
- **Design tokens** via Tailwind config — colors, spacing, breakpoints.

### Forms

- Always use **react-hook-form + zod**:
  ```typescript
  const schema = z.object({
    email: z.string().email(),
    name: z.string().min(2),
  });

  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });
  ```
- Server actions or API routes for submission.
- Show inline errors next to fields, not just at top.
- Toast on success/failure (use `sonner` or shadcn `<Toaster />`).

### Content

- **All copy lives in `/content/`** as typed TS objects:
  ```typescript
  // content/hero.ts
  export const hero = {
    badge: 'New approach',
    title: 'Headline here',
    subtitle: 'Sub copy',
    cta: 'Get started',
  } as const;
  ```
- **Never hardcode copy in components.** Always import from content.
- This enables i18n later and lets the copywriter edit without touching React.

### Images

- Always `next/image` with explicit `width`, `height`, `alt`.
- Use `priority` only for hero/above-fold images.
- WebP/AVIF preferred where possible.

### SEO

- `metadata` export in each `page.tsx`:
  ```typescript
  export const metadata: Metadata = {
    title: '...',
    description: '...',
    openGraph: { ... },
  };
  ```
- Structured data (JSON-LD) for Organization/Product if applicable.
- `sitemap.ts`, `robots.ts` in `app/` root.

## Performance budget (HARD limits)

| Metric | Target | Hard limit |
|--------|--------|------------|
| LCP (mobile) | <2.0s | <2.5s |
| INP | <100ms | <200ms |
| CLS | <0.05 | <0.1 |
| Lighthouse Performance | >95 | >90 |
| Lighthouse Accessibility | =100 | >95 |
| Initial JS bundle | <100KB gzip | <150KB |

If a feature pushes you over budget — **find a different approach**, don't ship it.

## What NOT to use (banned)

- jQuery, lodash, moment.js (use date-fns or native)
- Material UI, Chakra, Mantine (use shadcn/ui only)
- styled-components, emotion (use Tailwind)
- Bootstrap (any version)
- React Router (Next.js handles routing)
- Redux, MobX, Zustand (server components + URL state)
- Webpack/Rollup directly (Next.js abstracts)

## Telegram CTA pattern (mandatory for landings)

If the landing has Telegram CTA (very common for this agency):

```typescript
// lib/telegram.ts
export function telegramUrl(source: string, payload?: Record<string, string>) {
  const username = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || 'YourBotUsername';
  const startParam = source + (payload ? `__${encodeURIComponent(JSON.stringify(payload))}` : '');
  return `https://t.me/${username}?start=${startParam}`;
}

// components/shared/telegram-button.tsx
'use client';
import { telegramUrl } from '@/lib/telegram';
import { Send } from 'lucide-react';

export function TelegramButton({ source, label = 'Написать в Telegram' }: { source: string; label?: string }) {
  return (
    <a
      href={telegramUrl(source)}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-2 ..."
    >
      <Send className="w-4 h-4" />
      {label}
    </a>
  );
}
```

Every CTA must pass a `source` parameter so the agency can attribute traffic to specific sections.

## Visual style defaults (cinematic dark)

Unless the brief says otherwise, the agency's signature aesthetic:

- **Background:** `#050507` (near-black, slight cool tint)
- **Surface:** `#0c0c0f`
- **Accent:** `#7C5CFF` (deep purple) — primary CTA
- **Text primary:** `#F5F5F7`
- **Text secondary:** `#A1A1AA`
- **Border:** `rgba(255,255,255,0.06)`
- **Typography:** Inter Tight for everything, JetBrains Mono for code/numbers
- **Cinematic vibe:** subtle gradients, motion-controlled reveals, no garish colors

## Deployment

Default: **Vercel**. Add to project:
- `VERCEL_TOKEN` in pipeline env to deploy from CI
- Custom domain via Vercel dashboard

Alternative: **aeza subdomain** if client doesn't want Vercel:
- Static export via `output: 'export'` in `next.config.mjs`
- Sync to `/var/www/preview/<project-slug>/` on aeza
- nginx serves it under `<slug>.preview.hq.ai-delivery.shop`

## Testing minimum

For a landing v1 (no tests overkill):
- `pnpm build` passes
- `pnpm typecheck` (tsc --noEmit) passes
- Lighthouse mobile + desktop runs, all green
- Visual check on mobile + desktop
- Form submission test (if any)

E2E tests with Playwright optional for v1.

## Final notes

- **Lock dependencies.** `package.json` uses exact versions, not `^` ranges.
- **`.env.example`** must list every var the app reads, with placeholder values.
- **README.md** must include setup, dev, build, deploy steps for someone new.
- **First commit message:** `feat: initial landing page scaffold`.
