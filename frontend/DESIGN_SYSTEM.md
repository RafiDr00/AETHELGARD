# AETHELGARD FRONTEND DESIGN SYSTEM

Premium engineering control platform UI built with React, TypeScript, Vite, Framer Motion, and TailwindCSS.

## 🎯 Core Philosophy

The interface communicates:

- **Precision**: Accurate metrics, clear states, responsive feedback
- **Speed**: 120ms micro-interactions, 240ms normal transitions, 400ms panel animations
- **Technical Power**: Depth layers, glow effects, 3D elements, glassmorphism
- **System Intelligence**: Ambient animations, reactive elements, real-time data flow

Inspired by: Stripe, Linear, Vercel, Raycast, Datadog, Apple Developer Tools

---

## 📐 Design System Foundation

### Color Palette

| Purpose | Color | Usage |
|---------|-------|-------|
| Primary Accent | Cyan (#22d3ee) | Main CTAs, active states, data flow |
| Secondary Accent | Violet (#a78bfa) | Metadata, passive states, secondary actions |
| Success | Emerald (#34d399) | Happy path, completion, success states |
| Warning | Amber (#fbbf24) | Attention required, warnings |
| Danger | Red (#f87171) | Errors, failures, destructive actions |
| Background | #060a12 to #0d1421 | Depth layer backgrounds |

### 4px Grid System

All spacing uses 4px increments for precision and consistency:

```
4px   (1x)   → Tight spacing, icon adjacent elements
8px   (2x)   → Component internal padding
12px  (3x)   → Section padding, comfortable spacing
16px  (4x)   → Card padding, standard gap ★ STANDARD
20px  (5x)   → Larger gaps, panel margins
24px  (6x)   → Section margins, major spacing
32px  (8x)   → Large section spacing
```

### Motion Timing Hierarchy

Consistent animation timing throughout the app:

| Category | Duration | Use Case |
|----------|----------|----------|
| **Micro** | 120ms | Hover states, icon taps, button feedback |
| **Normal** | 240ms | Badge updates, state changes, list items |
| **Panel** | 400ms | Sidebar collapse, modal entrance, major transitions |
| **Slow** | 600ms | Ambient animations, camera movements, background shifts |

---

## 🧩 Component Library

### Form Components

#### Button

Primary interaction element with motion feedback.

```tsx
import { Button } from "@/components";

<Button variant="primary">Primary Action</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="danger">Delete</Button>
<Button isLoading={true}>Loading...</Button>
```

**Variants**: `primary` | `secondary` | `tertiary` | `danger` | `success` | `ghost`

**Sizes**: `sm` | `md` | `lg`

**Motion**: -1px hover lift, scale tap feedback

---

#### Input

Text input with validation and helper text.

```tsx
import { Input } from "@/components";

<Input label="API Key" placeholder="dev-..." />
<Input type="password" error={true} errorMessage="Invalid key" />
<Input helperText="Use lowercase only" />
```

**Props**: `label`, `helperText`, `icon`, `error`, `errorMessage`

---

#### Select

Dropdown with smooth animation and custom styling.

```tsx
import { Select } from "@/components";

<Select
  label="Scenario"
  options={[
    { value: "latency", label: "Payment Latency" },
    { value: "errors", label: "User Service Errors" },
  ]}
  value={selected}
  onChange={(e) => setSelected(e.target.value)}
/>
```

---

#### Checkbox / Radio

Custom form inputs with spring animations.

```tsx
import { Checkbox, Radio } from "@/components";

<Checkbox label="Enable notifications" />
<Radio name="group" label="Option 1" />
```

---

#### Tabs

Tabbed interface with Layout animation and active indicator.

```tsx
import { Tabs, TabPanel } from "@/components";

<Tabs
  tabs={[
    { id: "tab1", label: "Overview" },
    { id: "tab2", label: "Details" },
  ]}
  activeTab={active}
  onTabChange={setActive}
/>
<TabPanel isActive={active === "tab1"}>Content 1</TabPanel>
```

---

### Data Display Components

#### Card

Glassmorphic container with hover lift and glow options.

```tsx
import { Card } from "@/components";

<Card 
  title="Metrics" 
  variant="glass" 
  glow="cyan"
  hoverable={true}
  padding="lg"
>
  Card content
</Card>
```

**Variants**: `default` | `elevated` | `glass` | `dark`

**Glow**: `none` | `cyan` | `violet` | `success` | `error`

---

#### Badge

Status indicator with optional dot and animations.

```tsx
import { Badge } from "@/components";

<Badge status="running" label="Active" />
<Badge status="success" label="Complete" dot={true} />
```

**Auto-maps status**: `success`, `completed` → success | `error`, `failed` → danger | etc.

---

#### StatusIndicator / StatusBadge

Live status display with pulse and glow effects.

```tsx
import { StatusIndicator, StatusBadge } from "@/components";

<StatusIndicator status="running" label="Running" pulsing={true} />
<StatusBadge status="success" label="Healthy" />
```

---

#### Text / Typography

Semantic text components with consistent sizing.

```tsx
import { Text, Heading, Label, Code, Mono } from "@/components";

<Heading level={1}>Page Title</Heading>
<Label>Field Label</Label>
<Text size="md" color="secondary">Description</Text>
<Code>const x = 10;</Code>
<Mono>monospace text</Mono>
```

**Colors**: `primary` | `secondary` | `tertiary` | `muted` | `accent` | `success` | `danger` | `warning` | `code`

**Sizes**: `xs` | `sm` | `md` | `lg` | `xl` | `2xl`

---

### Overlay & Modal Components

#### Dialog

Animated modal with backdrop and keyboard support.

```tsx
import { Dialog } from "@/components";

<Dialog
  isOpen={isOpen}
  onClose={() => setIsOpen(false)}
  title="Confirm Action"
  description="Are you sure?"
  size="md"
>
  <p>Dialog content</p>
</Dialog>
```

**Sizes**: `sm` | `md` | `lg`

---

#### Alert

Notification component with variants and auto-dismiss.

```tsx
import { Alert, AlertGroup } from "@/components";

<Alert variant="success" title="Success">
  Operation completed successfully
</Alert>

<Alert variant="error" title="Error" closable={true}>
  Something went wrong
</Alert>
```

**Variants**: `success` | `error` | `warning` | `info`

---

### Layout Components

#### AppShell

Root layout container with particles, gradient, grid overlay.

- **Layer 0**: Particle field, radial gradients, dot-matrix grid
- **Layer 1**: Sidebar, main workspace
- **Layer 2**: Interactive elements
- **Layer 3**: Modals, overlays

---

#### Sidebar

Collapsible navigation with icon and label animation.

- **Collapsed**: 48px (icon only)
- **Expanded**: 220px (icon + label)
- **Transition**: 280ms ease-out

---

#### TopStatusBar

System status bar with HUD scanline effect.

---

#### ParticleCanvas

Animated particle field (65 particles, RAF loop).

---

## 🎬 Motion Patterns

### Framer Motion Variants

Pre-built animation patterns from `@/lib/motion.ts`:

```tsx
import { VARIANTS } from "@/lib/motion";

<motion.div variants={VARIANTS.fadeUp} initial="hidden" animate="visible">
  Content
</motion.div>
```

**Available variants**:
- `fadeUp`: Fade in while sliding up
- `slideLeft`: Slide in from left
- `scalePop`: Scale in with spring bounce
- `staggerContainer`: Stagger children animation
- `fastStagger`: Fast stagger for dense lists

### Motion Helpers

```tsx
import { motion, tapScale, liftScale, slideUp, fadeIn } from "@/lib/motion";

<motion.button {...tapScale}>Scale on tap</motion.button>
<motion.div {...liftScale}>Lift on hover</motion.div>
<motion.section {...slideUp(0.1)}>Slide up with delay</motion.section>
```

---

## 🎨 Animation Best Practices

1. **Hover Feedback**: Always use MICRO timing (120ms) for instant feedback
2. **State Changes**: Use NORMAL timing (240ms) for property updates
3. **Panel Transitions**: Use PANEL timing (400ms) for major layout changes
4. **Easing**: Use `easeOut` for entrance, `easeIn` for exit
5. **Performance**: Lazy load heavy components, avoid unnecessary re-renders

---

## ✅ Design Rules & Checklist

### Spacing
- ✓ All padding/margin uses 4px grid multiples
- ✓ Never use arbitrary spacing values
- ✓ Buttons: 8px vertical, 12px horizontal
- ✓ Cards: 16px padding by default

### Motion
- ✓ Hover uses 120ms timing
- ✓ State changes use 240ms timing
- ✓ Panel transitions use 400ms timing
- ✓ Ease out for entrance, ease in for exit

### Color
- ✓ Cyan is primary accent
- ✓ Violet is secondary accent
- ✓ Never use pure white or black (use #F1F5F9 / #060a12)
- ✓ Maintain 7+ color contrast for accessibility

### Typography
- ✓ Headings: Inter, bold, uppercase tracking
- ✓ Metadata: JetBrains Mono, semibold
- ✓ Minimum 11px for UI text
- ✓ Use semantic text components (Label, Code, Mono)

### Components
- ✓ All interactive elements must have hover state
- ✓ All interactive elements must have focus state
- ✓ Cards should be hoverable (lift on hover)
- ✓ Buttons should have tap feedback
- ✓ Use motion variants for consistency

---

## 📦 File Structure

```
src/
├── components/
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Select.tsx
│   │   ├── Checkbox.tsx
│   │   ├── Tabs.tsx
│   │   ├── Card.tsx
│   │   ├── Badge.tsx
│   │   ├── StatusIndicator.tsx
│   │   ├── Text.tsx
│   │   ├── Alert.tsx
│   │   ├── Dialog.tsx
│   │   ├── Tooltip.tsx
│   │   ├── MetricCard.tsx
│   │   ├── LoadingSpinner.tsx
│   │   ├── EmptyState.tsx
│   │   └── CollapsiblePanel.tsx
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   ├── Sidebar.tsx
│   │   ├── TopStatusBar.tsx
│   │   └── ParticleCanvas.tsx
│   ├── features/
│   │   ├── hero/
│   │   ├── pipeline/
│   │   ├── agents/
│   │   ├── metrics/
│   │   ├── incidents/
│   │   └── system/
│   └── index.ts (component exports)
├── lib/
│   ├── motion.ts (animation constants)
│   ├── design-system.ts (design tokens)
│   └── utils.ts (utilities)
├── styles.css (global styles)
└── App.tsx
```

---

## 🚀 Getting Started

### Install Dependencies

```bash
npm install
```

### Start Development Server

```bash
npm run dev
```

Browser will open to http://localhost:3000

### Build for Production

```bash
npm run build
```

### Type Checking

```bash
npx tsc --noEmit
```

---

## 🔍 Key Features

✅ **Zero Runtime Errors** – TypeScript strict mode, full type safety

✅ **Responsive Design** – Adapts to all screen sizes smoothly

✅ **Accessibility** – WCAG compliant, keyboard navigation, focus states

✅ **Performance** – Lazy loading, code splitting, optimized bundle

✅ **Glassmorphism** – Premium blur and transparency effects

✅ **3D Visualization** – React Three Fiber for agent network

✅ **Real-time Data** – TanStack Query for efficient data fetching

✅ **Dark Mode** – Dark mission-control aesthetic throughout

✅ **Animation Polish** – Framer Motion for smooth transitions

✅ **Premium Feel** – Handcrafted, not AI-generated components

---

## 📖 Documentation

- [Design System Documentation](./src/lib/design-system.ts)
- [Motion & Animation Utilities](./src/lib/motion.ts)
- [Color Palette & Tokens](./src/styles.css)
- [Component Library](./src/components/index.ts)

---

## 🎓 Philosophy

This frontend is built with the principle that **interface design matters**. Every pixel, every animation, every interaction has been thoughtfully considered to create a premium, professional experience worthy of a mission-control system.

The codebase is structured to encourage consistency and quality. New contributors are expected to follow the design system strictly and maintain the high standards established by this foundation.

**Result**: A platform that feels handcrafted, professional, and alive—something a senior frontend engineer would be proud to build.

---

**Last Updated**: March 11, 2026  
**Version**: 2.0  
**Status**: Production Ready ✅
