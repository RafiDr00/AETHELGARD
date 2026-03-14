# Frontend Development Checklist

Use this checklist when building new features to ensure compliance with the design system.

## 🎨 Design System Compliance

### Before Starting Development

- [ ] Read [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)
- [ ] Review [FRONTEND_SUMMARY.md](./FRONTEND_SUMMARY.md)
- [ ] Check [src/lib/component-examples.tsx](./src/lib/component-examples.tsx) for similar patterns
- [ ] Understand the 4px grid system and motion timings

### Component Building

#### Spacing & Layout
- [ ] All padding/margin uses 4px grid (4, 8, 12, 16, 20, 24, 32px)
- [ ] No arbitrary spacing values
- [ ] Gaps between elements follow the grid system
- [ ] Card padding is 16px by default (or specified variant)
- [ ] Button padding is 8px vertical, 12px horizontal

#### Motion & Animation
- [ ] Hover states use 120ms (MICRO) timing
- [ ] State changes use 240ms (NORMAL) timing
- [ ] Panel transitions use 400ms (PANEL) timing
- [ ] Entrance animations use `easeOut` easing
- [ ] Exit animations use `easeIn` easing
- [ ] All motion uses Framer Motion (not CSS-only)
- [ ] Motion constants imported from `@/lib/motion.ts`

#### Color & Visual Design
- [ ] Primary accent (cyan #22d3ee) used for main CTAs
- [ ] Secondary accent (violet #a78bfa) for metadata
- [ ] Emerald for success states, Amber for warnings, Red for errors
- [ ] Never use pure white or black (#F1F5F9 / #060a12)
- [ ] Text contrast passes WCAG AA (7:1 minimum)
- [ ] Glow effects use appropriate variant (`cyan`, `violet`, `success`, `error`)

#### Typography
- [ ] Headings: Inter, bold, uppercase tracking
- [ ] Metadata/Code: JetBrains Mono, semibold
- [ ] Minimum 11px font size for UI text
- [ ] Using semantic text components (`Text`, `Heading`, `Label`, `Code`)
- [ ] All text color using `Text` component with color prop

#### Component Building
- [ ] All interactive elements have `:hover` state
- [ ] All interactive elements have `:focus` state
- [ ] Using built-in Button, Input, Select, etc. (not custom)
- [ ] Cards are hoverable with lift effect (if appropriate)
- [ ] Buttons have tap scale feedback
- [ ] Forms have proper labels and error states
- [ ] Loading states use StatusIndicator or LoadingSpinner

### Code Quality

#### TypeScript
- [ ] 0 TypeScript errors (`npx tsc --noEmit`)
- [ ] All props properly typed
- [ ] No `any` types used
- [ ] No type assertions needed

#### React Best Practices
- [ ] Components under 250 lines (split if larger)
- [ ] Proper memo usage for performance
- [ ] No unnecessary re-renders
- [ ] Lazy load heavy components
- [ ] Proper key usage in lists

#### State Management
- [ ] Server state via TanStack Query
- [ ] UI state via Zustand (if global)
- [ ] Local state via `useState` for component-level
- [ ] No prop drilling (use context if needed)

#### Performance
- [ ] No console errors or warnings
- [ ] No memory leaks in `useEffect` cleanup
- [ ] Optimize re-renders with `useMemo` / `useCallback` where needed
- [ ] Images optimized and lazy loaded
- [ ] No unnecessary API calls

### Component Documentation

When building new components:

- [ ] Component has clear JSDoc comments
- [ ] Props interface is well-documented
- [ ] Usage example in code comments
- [ ] Component exported from `src/components/index.ts` (if appropriate)
- [ ] Consider adding to `src/lib/component-examples.tsx`

### Testing & Verification

Before committing:

- [ ] `npm run build` completes without errors
- [ ] Dev server runs without console errors (`npm run dev`)
- [ ] All pages load properly
- [ ] No TypeScript errors
- [ ] Responsive at mobile/tablet/desktop breakpoints
- [ ] Keyboard navigation works (Tab, Enter, Escape)
- [ ] Focus outlines visible

### Browser Compatibility

- [ ] Chrome/Edge latest ✓
- [ ] Firefox latest ✓
- [ ] Safari latest ✓
- [ ] Mobile Safari (iOS) ✓
- [ ] Mobile Chrome (Android) ✓

## 📐 Grid System Reference

```
4px   (1x)  → xs   → tight spacing
8px   (2x)  → sm   → button padding vertical
12px  (3x)  → md   → section padding
16px  (4x)  → base → card padding, standard gap ★
20px  (5x)  → lg   → larger gaps
24px  (6x)  → xl   → major spacing
32px  (8x)  → xxl  → large sections
```

## ⏱️ Motion Timing Reference

```
120ms (micro)  → Hover states, icon taps
240ms (normal) → Badge changes, state updates
400ms (panel)  → Sidebar, modals, major transitions
600ms (slow)   → Ambient animations, camera moves
```

## 🎨 Color Palette Quick Reference

```
Primary:    #22d3ee (cyan)
Secondary:  #a78bfa (violet)
Success:    #34d399 (emerald)
Warning:    #fbbf24 (amber)
Danger:     #f87171 (red)

Bg Base:    #060a12
Bg Surface: #0b0f1a
Bg Panel:   #0d1421
```

## 🧩 Component Import Quick Reference

```tsx
// Form controls
import { Button, Input, Select, Checkbox, Radio, Tabs } from "@/components";

// Data display
import { Card, Badge, StatusIndicator, Text, Heading } from "@/components";

// Modals & overlays
import { Dialog, Alert, AlertGroup } from "@/components";

// Layout
import { AppShell, Sidebar, TopStatusBar } from "@/components";

// Motion & design
import { VARIANTS, motion } from "@/lib/motion";
import { DESIGN_SYSTEM } from "@/lib/design-system";
```

## ✅ Pre-Commit Checklist

Before pushing code:

```bash
# 1. TypeScript check
npx tsc --noEmit

# 2. Build check
npm run build

# 3. Visual check
npm run dev
# → Open browser, manually test features
# → Check responsive design
# → Verify no console errors
```

## 📚 File References

When building features, keep these files handy:

1. `[DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)` — Design principles & rules
2. `[FRONTEND_SUMMARY.md](./FRONTEND_SUMMARY.md)` — What's been built
3. `[src/lib/design-system.ts](./src/lib/design-system.ts)` — Design tokens
4. `[src/lib/motion.ts](./src/lib/motion.ts)` — Motion helpers
5. `[src/lib/component-examples.tsx](./src/lib/component-examples.tsx)` — Usage examples
6. `[src/components/index.ts](./src/components/index.ts)` — Available components

---

**Remember**: Consistency is premium. Every new feature should feel like it belongs to the same handcrafted system.
