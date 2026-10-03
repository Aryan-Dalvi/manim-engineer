# ADR 0008: The presenter deck is Reveal.js built from section clips, not manim-slides

## Status

Accepted (2026-09-17). The deck-scope bullet is superseded by ADR 0009.

## Context

Every beat is already a Manim section and is published as its own MP4
(ADR 0003, ADR 0006). The output research recommended manim-slides for HTML and
PPTX decks, but manim-slides records slides only for scenes that subclass its
`Slide` class. Generated scenes subclass `Scene`, and the Tier 0 structure check
rejects a class whose base name does not end in `Scene`, so adopting it would
change the code-generation contract, the probe and every scene fixture. The
PPTX deck was already built with python-pptx for the same reason.

A presenter also needs the deck to work without a network, and the deck's text
comes from model-written titles and narration.

## Decision

- `output.build_revealjs` writes one HTML deck from published bundles: a title
  slide, then one slide per beat whose section clip autoplays muted, with the
  beat's narration as speaker notes. Slides follow entry order, then beat order,
  so the slide count equals the beat count.
- Reveal.js 6.0.2 is vendored unmodified under `output/assets/revealjs`
  (`reveal.js`, `reveal.css`, `plugin/notes.js`, `LICENSE`; sizes and SHA-256 in
  its `ATTRIBUTION.md`) and copied beside every deck with relative links.
- No Reveal theme is loaded. The deck sets the 42px base font that Reveal
  6.0.2's black theme declares, because em sizes otherwise follow the browser's
  16px default and captions become unreadable.
- The template autoescapes every value.
- `pipeline` rebuilds `outputs/<run>/deck.html` whenever it rebuilds the gallery,
  from accepted and `needs_human` concepts in plan order. `needs_human` slides
  are marked "needs review". The deck is removed when nothing is presentable, and
  only a URL source is ever shown as its subtitle, never a local input path.

## Consequences

- **Benefit:** generated code and verification are unchanged; a deck presents
  offline and survives moving the run directory.
- **Tradeoff:** no manim-slides behaviour such as looping or reversing a slide;
  each beat is a clip that plays once.
- **Tradeoff:** upgrading Reveal.js means replacing every vendored file together
  and refreshing the `ATTRIBUTION.md` table.
- **Follow-up:** once approval pins exist, the deck should include approved
  concepts rather than every accepted or `needs_human` one.
