---
name: Gallery Mono
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1b1b1b'
  surface-container: '#1f1f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353535'
  on-surface: '#e2e2e2'
  on-surface-variant: '#c4c7c8'
  inverse-surface: '#e2e2e2'
  inverse-on-surface: '#303030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c6c6c7'
  primary: '#ffffff'
  on-primary: '#2f3131'
  primary-container: '#e2e2e2'
  on-primary-container: '#636565'
  inverse-primary: '#5d5f5f'
  secondary: '#c6c5cf'
  on-secondary: '#2f3038'
  secondary-container: '#4a4b53'
  on-secondary-container: '#bcbbc5'
  tertiary: '#ffffff'
  on-tertiary: '#2f3130'
  tertiary-container: '#e2e3e0'
  on-tertiary-container: '#636563'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c7'
  on-primary-fixed: '#1a1c1c'
  on-primary-fixed-variant: '#454747'
  secondary-fixed: '#e3e1ec'
  secondary-fixed-dim: '#c6c5cf'
  on-secondary-fixed: '#1a1b22'
  on-secondary-fixed-variant: '#46464e'
  tertiary-fixed: '#e2e3e0'
  tertiary-fixed-dim: '#c6c7c4'
  on-tertiary-fixed: '#1a1c1b'
  on-tertiary-fixed-variant: '#454746'
  background: '#131313'
  on-background: '#e2e2e2'
  surface-variant: '#353535'
typography:
  headline-xl:
    fontFamily: JetBrains Mono
    fontSize: 64px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.04em
  headline-lg:
    fontFamily: JetBrains Mono
    fontSize: 40px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: JetBrains Mono
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
  headline-md:
    fontFamily: JetBrains Mono
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
  body-lg:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1.0'
    letterSpacing: 0.1em
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.4'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-sm: 16px
  margin-md: 40px
  margin-lg: 80px
  container-max: 1440px
---

## Brand & Style
The design system embodies a "Premium Lab" aesthetic—a sophisticated intersection of academic rigor and advanced artificial intelligence. It leverages a **Minimal Brutalist** foundation characterized by structural integrity, strict monochromatic harmony, and technical precision.

The target audience consists of researchers, academics, and high-level thinkers who require a focused, distraction-free environment that feels both high-end and functional. The emotional response should be one of "Deep Intentionality"—where every pixel feels computed and purposeful. Visual signatures include high-contrast interactions, thin "architectural" strokes, and sophisticated 3D glass layers that suggest depth without sacrificing the flat, brutalist core.

## Colors
The palette is strictly monochromatic to enforce a scholarly focus. The primary mode is **Dark**, utilizing `#000000` as the absolute void for the canvas, with `#0E100F` providing subtle differentiation for container backgrounds. 

Pure `#FFFFFF` is reserved for primary typography and high-contrast actions, ensuring maximum readability and "impact" against the dark background. Grays are used strategically to denote hierarchy and "technical metadata," while semi-transparent white layers create the glass effects necessary for the high-end tech feel.

## Typography
This design system employs a dual-font strategy to balance technical utility with editorial sophistication. 

**JetBrains Mono** is the "Structural" font, used for headlines and technical labels to evoke the feeling of a high-end IDE or research paper. It should be typeset with tight letter-spacing in large sizes to feel aggressive and modern. 

**Geist** serves as the "Interface" font, handling all body copy and UI elements with its neutral, highly legible sans-serif characteristics. It ensures that the academic content remains the focus, providing a clean counterpoint to the more expressive mono headlines.

## Layout & Spacing
The layout follows a **Fixed Grid** philosophy rooted in a 4px baseline. On desktop, content is housed within a 1440px container using a 12-column grid. 

Margins are generous to provide "breathability" amidst the high-contrast elements. Technical data displays should utilize "Micro-grids" (sub-layouts of 8px increments) to maintain a structured, mathematical appearance. Transitions between sections should use staggered entrances, where elements appear with a 0.05s delay relative to their vertical position.

## Elevation & Depth
Depth is achieved through **Glassmorphism** and **Tonal Layering** rather than traditional shadows. 

1.  **Base Layer:** Solid `#000000`.
2.  **Container Layer:** Subtle `#0E100F` with a `1px` border of `#27272A`.
3.  **Glass Layer:** Semi-transparent white (`rgba(255, 255, 255, 0.03)`) with a `12px` backdrop-blur. 
4.  **Interaction Layer:** Hover states should trigger a "glow" effect—a subtle, non-diffused 1px white border or a sharp increase in surface opacity.

Shadows, if used, are extremely crisp and low-blur (e.g., `4px 4px 0px rgba(255,255,255,0.1)`), reinforcing the brutalist influence.

## Shapes
Shapes are defined by **Softened Precision**. All primary UI elements (buttons, inputs, cards) utilize an `8px` (0.5rem) radius. This introduces a sophisticated, modern "Rounded" feel that softens the harshness of the Brutalist aesthetic while maintaining structural clarity.

Larger containers may use up to `16px` or `24px` for higher-order surfaces, ensuring that the interface feels approachable and high-end. Small interactive elements retain this consistency to provide a balanced tactile perception.

## Components
-   **Buttons:** Rectangular with an `8px` radius. Primary buttons are solid `#FFFFFF` with `#000000` text. Secondary buttons are transparent with a `1px` white border.
-   **Input Fields:** Ghost-style inputs with an `8px` radius and a bottom border of `1px #27272A` that transforms into a full white box outline on focus.
-   **Cards:** Use the "surface-glass" variable with an `8px` radius. Borders are `1px` and "technical" (low contrast). Header areas of cards should be separated by a `1px` horizontal rule.
-   **Chips/Tags:** Monospaced text in `label-caps` style, wrapped in a thin white border with an `8px` radius and no fill.
-   **Motion:** Follow `motion.dev` patterns. Hovering over a card should slightly scale the background glass layer while the border remains static. Stagger list items on page load using a `spring` transition for a tactile, responsive feel.
-   **Data Visualizations:** Use strictly monochrome charts—varying shades of gray and white textures (dots, slashes) to differentiate data sets instead of color.