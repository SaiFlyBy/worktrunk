# Structural Mutation and Code Intelligence

Mission Control must distinguish semantic/source-structure mutation from blind text editing.

Tree-sitter, compiler ASTs, language servers, schema-aware rewriters, refactoring engines, and equivalent structural systems are examples of evidence-bearing implementation mechanisms. No specific parser is universally mandatory, but mutation strategy must match the structure and risk of the target.

## Structural-first law

When a change depends on symbols, syntax, scopes, imports, call relationships, configuration structure, API signatures, or other machine-readable structure, prefer a structural mutation path over regex/string replacement.

Allowed structural engines include:

- compiler/parser ASTs;
- Tree-sitter or equivalent concrete syntax trees;
- language-server/refactoring APIs;
- schema-aware transformation engines;
- queryable IRs;
- generated-code owners that can regenerate the surface deterministically.

Text-only mutation is allowed when the surface is genuinely textual, when no reliable structural engine exists, or when the bounded change is demonstrably safer as text. High-risk text-only mutation requires an explicit rationale plus hostile verification for overmatch, undermatch, formatting damage, and accidental changes inside comments/strings/generated regions.

## Mutation plan

For each nontrivial code/config mutation surface, record:

- language/format and owned paths;
- structural engine and exact parser/tool version when one is used;
- selectors or semantic identities being changed;
- expected affected symbols/nodes/files;
- expected unaffected regions;
- generated/vendor/binary boundaries;
- preservation requirements for comments, formatting, ordering, stable IDs, and public interfaces;
- fallback strategy when parsing/analysis fails;
- validation that the transformation is idempotent or intentionally non-idempotent;
- post-mutation structural checks and behavioral tests.

## Parse failure and ambiguity

Parse failure is evidence. Do not silently fall back from a structural plan to regex because a parser rejected the project. Record the failure, determine whether the grammar/tool/version is wrong or the target contains unsupported/invalid syntax, and either repair the analysis path or authorize a bounded fallback with compensating verification.

Ambiguous symbol resolution, partial language support, generated code, macro systems, dynamic dispatch, reflection, metaprogramming, templating, or preprocessor behavior must be represented as uncertainty rather than guessed away.

## Diagnostics and repair

Structural engines may be used read-only to build diagnostic facts before any mutation. A repair system may compare expected component/spec structure with observed syntax/semantic structure and propose changes. Automatic repair is permitted only when the compiled mutation contract authorizes it and verification can distinguish a correct repair from a syntactically valid but semantically wrong edit.

## Incremental analysis

Where the parser/analysis substrate supports incremental updates, preserve stable syntax/semantic identities and changed-range information rather than rebuilding global understanding after every edit. Incrementality is a performance mechanism, never a reason to skip full qualification of affected behavior.

## Tool provenance

If an external parser, grammar, transformation recipe, or refactoring engine materially influences implementation, bind its exact source/version and license/rights posture in provenance. Directly reused grammars/recipes obey their own license obligations. Behavioral inspiration without authorized code reuse remains independently implemented.
