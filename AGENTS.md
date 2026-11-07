# Agent Guidelines & Engineering Constitution for MFHelper

## 1. Zero Assumptions & Design Clarification Policy
- **Never Assume Architectural Choices**: If a requirement has multiple valid implementations, data schemas, API contracts, formulas, or integration patterns, you MUST explicitly state the trade-offs and ask the user before writing code.
- **Clarify Ambiguities Early**: If inputs, outputs, or dependencies are not 100% specified, ask targeted questions. Do not pick a default silently.

## 2. Hard Stop Gate: Design First, Code Second
- When a feature, track, or non-trivial change is requested, you must follow the OpenSpec pattern:
  1. Create `openspec/changes/<feature_name>/` (`proposal.md`, `design.md`, `tasks.md`).
  2. **STOP IMMEDIATELY**: Present the design questions, key trade-offs, and open choices to the user.
  3. **DO NOT WRITE CODE OR TESTS** until the user explicitly reviews, answers the questions, and approves the design.

## 3. Sandboxing & Safe Testing
- Never write to or modify production Google Sheets or live state files during testing.
- Always use the `--dev` flag for verification runs.
- Run `pytest tests/` and verify all tests pass before completing any task.

## 4. Communication Style
- Use simple, clear, everyday English. Keep sentences short and direct.
- Start with the direct answer. Prefer short paragraphs and bullets; use tables when comparing options.
- Explain technical terms in plain language. Explain steps in order and why they are needed.
- Do not assume the user already understands a concept because it is technical. Use practical examples when they help.
- Keep technical details accurate. Simplify the explanation, not the technical meaning.
- Avoid unnecessary jargon, repetition, long introductions, and conclusions.
- For follow-up questions, answer the specific question without restarting the full explanation.
