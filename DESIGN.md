# Design System — arche

The visual language of the arche documentation site and any surface that
represents the project. Read this before making a visual or UI decision.

## Product Context

- **What this is:** an open-source engine that finds entities in messy,
  multilingual data, works out which real-world thing each one refers to,
  protects them under the law that applies, and signs every decision.
- **Who it's for:** two audiences with one surface. Data and compliance
  engineers evaluating whether to trust the library, and AI agents calling
  it as a tool. Both need the same thing: unambiguous, verifiable statements.
- **Space:** developer infrastructure — entity resolution, record linkage,
  data protection. Peers by posture: OpenSanctions, Splink, dbt circa 2018.
- **Project type:** documentation site for a Python library.

## The memorable thing

**Software that refuses rather than guesses.**

Every design decision serves this. arche's differentiator is not that it
answers more; it is that its answers can be checked, and that it returns
`unknown` when the evidence does not support a verdict. A design that reads
as confident marketing undercuts the one thing the product is selling.

Practical consequence: no persuasion patterns. No gradient CTAs, no
social-proof logo walls, no "trusted by" bars, no animated counters. Evidence
is the whole aesthetic. When we want the reader to believe something, we show
them the output and the citation, not an adjective.

## Aesthetic Direction

- **Direction:** Industrial / utilitarian, with editorial typography.
  A measurement instrument, not a landing page.
- **Decoration level:** minimal. Type, rule lines, and one structural colour
  do all the work. No illustration, no texture, no blobs.
- **Mood:** precise, sober, legible under scrutiny. It should feel closer to
  a well-set statute or a lab notebook than to a SaaS homepage.
- **Deliberate departure from the category:** dev-tools sites converge on
  blue or violet, a sans display face, and a three-column feature grid.
  arche uses deep green, a serif display, and a four-verb pipeline strip.
  The serif is the risk and it is the point: this is a product about
  records, names, and law, and a serif says *record* in a way no grotesque
  does.

## Typography

- **Display / headings:** **Instrument Serif** — editorial, high-contrast,
  evokes documents and law. Carries the "record" idea the product is about.
  Used for h1 and h2 only.
- **Body / UI:** **Instrument Sans** — designed alongside Instrument Serif,
  so the pairing is native rather than assembled. Highly legible at small
  sizes, neutral enough to disappear behind the content.
- **Code / data:** **JetBrains Mono** — retained from the existing system.
  Good at 14px, clear zero, wide language coverage for multilingual samples.
- **Deliberately not used:** Inter, Roboto, Space Grotesk, system-ui. Every
  AI-generated dev-tools site converges on these; using them signals that no
  typographic decision was made.
- **Loading:** self-hosted or Google Fonts `display=swap`. Body must remain
  readable during font load — no invisible-text flash.

### Scale

Material sets the root to 125%, so `1rem` = 20px. Values below are the
computed pixel sizes that result.

| Role | Size | Line height | Notes |
|---|---|---|---|
| h1 | 42px | 1.12 | was 31.2px — hierarchy was too flat against h2 |
| h2 | 28px | 1.2 | |
| h3 | 20px | 1.3 | |
| body | 16.4px | 1.68 | was 15.6px |
| code block | 14.4px | 1.6 | unchanged; already correct |
| table | 15px | 1.5 | was 14.4px — too small for dense data |
| caption / meta | 13.6px | 1.5 | |

**Measure is the real constraint.** The previous system set content width to
880px at 15.6px, giving ~100 characters per line — well past the 45–75 that
reads comfortably. Prose columns cap at **68ch**. Tables and code blocks are
allowed to exceed that and scroll within their own container, because
truncating a code line is worse than a wide block.

## Colour

- **Approach:** restrained. One structural colour, two state colours,
  everything else neutral. Colour carries meaning here — it is not decoration.
  If a hue appears, it should be answerable to the question "what state does
  that mean?"

### Light

| Token | Value | Use |
|---|---|---|
| `--arche-ink` | `#131a18` | body text |
| `--arche-ink-muted` | `#55625d` | secondary text, captions |
| `--arche-surface` | `#ffffff` | page ground |
| `--arche-surface-sunken` | `#f4f7f5` | code blocks, table headers, cards |
| `--arche-line` | `#dde5e1` | rules, borders |
| `--arche-green-900` | `#12241f` | header, footer |
| `--arche-green-700` | `#1f3d36` | primary — retained from existing brand |
| `--arche-green-500` | `#2f6f63` | links, accent — retained |
| `--arche-green-100` | `#e4efea` | tints, active nav |

### Dark

Not a filter over light. Surfaces are redesigned and the accent is lifted so
it keeps contrast against a dark ground.

| Token | Value |
|---|---|
| `--arche-ink` | `#e6ede9` |
| `--arche-ink-muted` | `#8ea099` |
| `--arche-surface` | `#0e1614` |
| `--arche-surface-sunken` | `#131f1c` |
| `--arche-line` | `#243330` |
| `--arche-green-500` | `#5cab9b` (lifted) |
| `--arche-green-100` | `#1b2f2a` |

### State colours — the abstention palette

These exist because the product's central behaviour is refusing to guess.
The three verdict states get three colours, used consistently everywhere a
decision is displayed.

| State | Light | Dark | Meaning |
|---|---|---|---|
| `match` / verified | `#2f6f63` | `#5cab9b` | the engine decided, and signed it |
| `review` / `unknown` | `#9a6410` | `#d99b3c` | honest abstention — evidence insufficient |
| `refused` / denied | `#8c2f2a` | `#d97a72` | policy blocked this; fail-closed |

`review` is amber, not red. It is not an error. Colouring abstention as
failure would contradict the product thesis.

## Spacing

- **Base unit:** 4px.
- **Density:** comfortable. This is reference material people read for a long
  time, not a dashboard they scan.
- **Scale:** 2xs(4) xs(8) sm(12) md(16) lg(24) xl(40) 2xl(64) 3xl(96)
- Section rhythm: h2 gets 2.5× the space above it that it gets below, so
  sections read as separated rather than as a uniform stream. The previous
  system used a flat 2.1rem top margin and everything ran together.

## Layout

- **Approach:** grid-disciplined. Documentation is not the place for
  asymmetry.
- **Prose measure:** 68ch. **Full content column:** 960px.
- **Border radius:** 3px for code and inputs, 6px for cards and admonitions,
  0 for rules and table edges. Nothing is pill-shaped. Bubble radii read as
  consumer software and undercut the instrument feel.
- **Home page** is a composition, not a document: a hero that states the
  positioning, a four-verb strip that shows the pipeline as a system, one
  real code example with real output, and honest release status. Everything
  else is navigation.

## Motion

- **Approach:** minimal-functional. Transitions exist to explain a state
  change and for nothing else.
- **Duration:** 120ms for hover and focus, 200ms for theme change.
- **Easing:** `ease-out` on enter, `ease-in` on exit.
- No scroll-driven animation, no entrance choreography, no parallax. A page
  that performs while you are trying to read a signature format is working
  against its own content.
- Honour `prefers-reduced-motion` — disable all non-essential transitions.

## Positioning copy

The canonical statement. Use verbatim; do not paraphrase into a new variant.

> **Know what's real.**
>
> The open engine for messy, multilingual data. Find the entities, resolve
> who they actually are, protect them under the law that applies, and sign
> every decision.

Three competing formulations existed across the repo before v0.3.0a1
("the identity data engine for Africa", "African PII detection that cites the
law it enforces", "the open decision layer for real-world entities"). They are
superseded. Africa is the **calibration credential and the wedge** — the
hardest identity data in the world, which is why the engine is good — not the
scope. Say so; do not scrub the African coverage claims, which are real and
are an asset.

### The claims ladder governs hero copy

Hero and landing copy may only make claims that have shipped. Registry
adapters, engine routing, and hypervector matching are roadmap language and
must be labelled as such wherever they appear. This is a design constraint,
not only an editorial one: if a claim cannot be checked, it does not get
hero treatment.

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-07 | Initial design system | Created by `/design-consultation` during the v0.3.0a1 release review. |
| 2026-08-07 | Serif display (Instrument Serif) | Deliberate category departure. The product is about records, names, and statutes; a serif carries that. Every peer uses a grotesque. |
| 2026-08-07 | Dark mode added | The site shipped with a single `scheme: default` and no toggle. Table stakes for developer documentation. |
| 2026-08-07 | Prose measure capped at 68ch | Measured the live site at 880px / 15.6px ≈ 100 characters per line. Too wide to read comfortably. |
| 2026-08-07 | Amber for `review`, not red | Abstention is the product's differentiator, not a failure state. Colouring it as an error would contradict the thesis. |
| 2026-08-07 | Retained the existing greens | `#1f3d36` / `#2f6f63` are already the project's colours and are genuinely distinctive in a category saturated with blue and violet. The problem was that they appeared in the header and then vanished, not that they were wrong. |
