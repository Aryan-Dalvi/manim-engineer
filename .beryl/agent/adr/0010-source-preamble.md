# ADR 0010: A source preamble compiles every TeX string the same way in every gate

## Status

Accepted (2026-10-03)

## Context

ADR 0007 left a follow-up: the arXiv adapter stored a paper's macro definitions
in `Provenance.macros`, and nothing applied them when TeX was compiled.
Measuring the 54 source equations of arXiv 2603.03251 showed the gap was wider:

| What compiled each equation | Pass |
| --- | --- |
| Tier 0 LaTeX precompile | 12 / 54 |
| Manim (Tier 1 probe and render) | 48 / 54 |
| Manim + the paper's 447 macro definitions | 48 / 54 |
| Manim + the paper's math packages and macros | 54 / 54 |

- The six failures all used `\coloneqq` from `mathtools`. That paper's
  equations use none of its macros. Its packages are what they need.
- Tier 0 kept a hand-copied preamble with eight packages Manim 0.19 does not
  load, and typeset `MathTex` as `$\displaystyle …$` instead of `align*`. So it
  rejected every `&`-aligned equation (39 of the 54) and split-part `MathTex`,
  and it accepted `\qty`, which the renderer rejects.
- ADR 0007 makes a missing source equation fatal and tells the model to write it
  verbatim. Tier 0 then failed that literal, and changing it tripped the fidelity
  gate. The fallback scene embeds the same equations, so paper concepts ended
  `rejected` after spending their repair budget.
- The adapter read definitions with a one-line regex, so one split across lines
  was cut off.

## Decision

**Tier 0 compiles what Manim compiles.**

- Tier 0 builds each document with Manim's `TexTemplate` API and the
  environment each class uses (`align*` for `MathTex`, `center` for `Tex` and
  `Title`, none for `BulletedList`).
- It compiles the joined string and then each part (`{{ }}` groups, isolated
  substrings), after Manim's own clean-up of each string
  (`SingleStringMathTex._get_modified_expression`), with Manim's compile
  command.
- A call that passes its own `tex_template` is left to Tier 1.
- A parity test pins Tier 0's verdict to the probe's.

**The source preamble** is `Provenance.packages` plus `Provenance.macros`:

- `core.preamble` parses definitions brace-matched (`\newcommand`,
  `\renewcommand`, `\providecommand`, `\DeclareMathOperator`, `\def`, `\gdef`,
  `\let`).
- It drops any definition that reaches files or the shell, changes how TeX
  reads input, or builds a command name from characters: `\input`, `\write`,
  `\catcode`, `\csname`, `^^` escapes, `@` internals and the like.
- Each kept definition has a safe form, so a paper that defines a command
  Manim's preamble has, or renews one it lacks, does not stop the preamble:
  - `\newcommand` and `\renewcommand` become `\providecommand{\x}{}\renewcommand…`.
  - `\DeclareMathOperator{\x}` gets `\let\x\relax` before it.

**The package allowlist** is `amsfonts`, `bm`, `dsfont`, `mathrsfs`,
`mathtools`, `physics`, `xcolor` and `xspace`. Each one compiles under Manim's
template in a test. Package options are dropped. `Provenance.packages` rejects
any other name, so a hand-edited plan cannot load one.

**The header in the scene file** carries the preamble:

```python
# source-preamble: generated from the plan; edits here are replaced
use_source_preamble(packages=["mathtools"], definitions=[r"\newcommand{\KL}{D_{\mathrm{KL}}}"])
# end source-preamble
```

- Generation writes it after the imports, from the plan, on every normalize and
  in the fallback scene. It replaces whatever the model wrote there, and holds
  only the definitions the code uses, plus their dependencies.
- The kit applies it when the scene is imported, so the probe child, the render
  subprocess and a hand-run `manim` all use it. Packages the machine lacks
  (`kpsewhich`) are left out.
- Tier 0 reads the call from the AST and builds its template with the kit's
  `source_tex_template`. It compiles the preamble once before any literal:
  - A broken definition is one `source_preamble` finding.
  - A missing package is a warning with the `tlmgr` command.
  - A package off the allowlist, or a header that is not literal, is fatal.
- The fidelity gate ignores the header, which is never drawn.

**The arXiv adapter** also inlines `.sty` files the paper ships, once each, with
comments stripped first.

**Rejected alternatives:**

- *Passing a template through the probe and render adapters.* Every call site
  must pass it, one miss brings the divergence back, and scene files no longer
  render on their own.
- *Having the kit read an environment variable or sidecar file.* This is hidden
  coupling, and Tier 0 needs separate plumbing.
- *Asking the model to pass `tex_template=`.* The result varies between runs, and
  Tier 0 cannot check it.
- *Injecting every definition.* That is 11 KB per scene and per repair prompt,
  and one broken definition would break every equation.

## Consequences

- **Benefit:** on that paper, Tier 0 and the probe now both compile all 54 source
  equations. An end-to-end test of an arXiv-shaped paper is accepted on the
  first attempt, where it used to be rejected after four.
- **Benefit:** for every input type, Tier 0 stops rejecting `&` alignment and
  split-part `MathTex`. It also catches commands outside Manim's preamble one
  probe earlier.
- **Tradeoff:** importing a scene sets Manim's global config. That is safe with
  one scene per process (the probe child, the render subprocess), and the inline
  probe runs inside `tempconfig`.
- **Tradeoff:** the same scene renders with or without a package, depending on
  the machine's TeX install. Tier 0 warns about it, and `doctor` lists missing
  packages.
- **Tradeoff:** a definition that fails in TeX is terminal for any source
  equation that needs it.
- **Tradeoff:** `eqnarray` equations are typeset in `align*`, so `&=&` gets a
  column gap the paper does not have.
- **Tradeoff:** Tier 0 calls a private Manim method. ManimCE is pinned to 0.19
  (ADR 0002), and the parity test fails if an upgrade changes it.
- **Follow-up:** verbatim source equations still reach `MathTex` without the
  deny-list.
- **Follow-up:** `\NewDocumentCommand` definitions are not extracted.
- This resolves ADR 0007's follow-up and refines the Tier 0 LaTeX precompile in
  ADR 0004.
