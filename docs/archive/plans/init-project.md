# Plan: /init-project Orchestrator and /generate-claude-md Skills

> Source PRD: GitLab issue #1 — feat: /init-project orchestrator and /generate-claude-md skills

## Architectural Decisions

Durable decisions that apply across all phases:

- **Skill file format**: `core/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`), optional `references/` subdirectory for bundled domain knowledge
- **CLAUDE.md section structure**: Architecture, Commands, Code Style, Methodology — derived from project.md analysis + interview answers
- **Interview pattern**: AskUserQuestion with codebase-first findings presented for confirm-or-correct. Four domains: Stack, Style, Methodology, Guardrails
- **Hook presets structure**: Organized by detected stack (Python, JS/TS, General) in a reference markdown file. Offered via multiSelect during interview.
- **Delegation pattern**: Orchestrator invokes downstream skills by name (`/project-context`, `/generate-claude-md`) and generates hooks directly. Passes relevant interview context as conversational briefing. Each delegated skill runs its own flow.
- **Error handling**: Skip-and-report with failure classification (see table below). Expected state transitions (e.g., empty repo) trigger mode switches, not skip reports. Actual failures (e.g., missing Python) are skipped and reported.
- **Build inclusion**: Core skills are auto-included via `"skills": "all"` in preset manifests. No manifest edits needed for new core skills.
- **Gap detection**: On partial existing setup, check for each component (`.claude/`, `project.md`, `CLAUDE.md`, hooks, `settings.json`) and ask user whether to update or skip before proceeding.
- **Context passing**: When the orchestrator delegates to `/generate-claude-md`, it passes pre-supplied context (tech stack, code style, methodology, commands). The downstream skill detects whether context was provided and adjusts its flow accordingly (pre-filled vs. standalone analysis).

### Failure vs. State-Transition Table

| Delegation | Expected State Transition | Actual Failure (skip and report) |
|---|---|---|
| `/project-context` | Empty repo detected → switch to interview-heavy mode | Codebase analysis crashes or produces malformed output |
| `/generate-claude-md` | No project.md exists → interview-only skeleton mode | Skill cannot write to project root (permissions) |
| Hook generation | User selects no guardrails → skip hooks gracefully | Cannot create `.claude/hooks/` directory; cannot write settings.json |

---

## Phase 1: /generate-claude-md Standalone Skill

**User stories**: 9, 10, 12

### What to build

A standalone skill that generates `CLAUDE.md` at the project root. It reads `.claude/docs/project.md` (if it exists) as its primary input, plus optional interview context passed by the orchestrator or provided by the user. The skill analyzes project.md to extract architecture, commands, code style, and methodology, then produces a well-structured CLAUDE.md.

**Dual-path context detection**: If invoked with pre-supplied context (tech stack, code style, methodology, commands — as provided by the `/init-project` orchestrator), use that context to pre-fill CLAUDE.md sections. If invoked standalone (no pre-supplied context), read project.md and ask clarifying questions about anything that cannot be inferred.

The skill checks if CLAUDE.md already exists and confirms before overwriting. It also verifies that project.md exists — if not, it suggests running `/project-context` first (or proceeds with interview-only mode if the user wants a skeleton CLAUDE.md).

### Acceptance criteria

- [ ] `core/skills/generate-claude-md/SKILL.md` exists with valid YAML frontmatter (name, description)
- [ ] Skill reads `.claude/docs/project.md` and produces a `CLAUDE.md` at project root
- [ ] Generated CLAUDE.md includes sections: project description, Architecture, Commands, Code Style, Methodology
- [ ] Skill checks for existing CLAUDE.md and asks before overwriting
- [ ] Skill handles missing project.md gracefully (suggests /project-context or proceeds with interview-only)
- [ ] Skill accepts optional interview context (tech stack, conventions, methodology preferences) to pre-fill sections
- [ ] Generated CLAUDE.md references `.claude/docs/project.md` for detailed project context

---

## Phase 2: /init-project Orchestrator and Reference Files

**User stories**: 1, 2, 3, 4, 5, 6, 7, 8, 11

### What to build

The main orchestrator skill that bootstraps the full `.claude` ecosystem in a single session. Five phases execute in order:

1. **Detect Gaps** — Check for existing `.claude/`, `project.md`, `CLAUDE.md`, hooks, `settings.json`. For each existing component, ask the user whether to update or skip.
2. **Analyze** — Delegate to `/project-context` for codebase analysis AND project.md generation. If empty repo detected (no source files), skip analysis and flag for interview-heavy mode. For empty repos, generate a minimal project.md from interview answers in Phase 3 instead.
3. **Interview** — Custom confirm-only interview across Core 4 domains (Stack, Style, Methodology, Guardrails). Present codebase findings from Phase 2 for user to confirm or correct. For empty repos, switch to open-ended questions about planned stack and conventions. Guardrails domain uses stack-specific hook presets from reference file.
4. **CLAUDE.md** — Delegate to `/generate-claude-md` with interview context pre-supplied.
5. **Hooks** — Generate protection hooks directly using guardrail decisions from interview. Creates `.claude/hooks/protect-files.py` and wires it into `.claude/settings.json`. Does not delegate to `/setup-hooks` (which has no orchestrated mode). If hook generation fails, skip and log.

Wrap-up: Present summary of all phases (succeeded/skipped/failed). Offer to commit generated files via `/commit`.

Two reference files support the interview:
- `references/interview-domains.md` — Question templates for each of the Core 4 domains, including confirm-only patterns and empty-repo variants
- `references/hook-presets.md` — Stack-specific protection presets (Python, JS/TS, General) with file patterns and descriptions

### Acceptance criteria

- [ ] `core/skills/init-project/SKILL.md` exists with valid YAML frontmatter (name, description)
- [ ] `core/skills/init-project/references/interview-domains.md` exists with Core 4 domain definitions
- [ ] `core/skills/init-project/references/hook-presets.md` exists with stack-specific presets for Python, JS/TS, and General
- [ ] Phase 1 (Detect Gaps) checks for `.claude/`, `project.md`, `CLAUDE.md`, hooks, `settings.json` and asks user about existing components
- [ ] Phase 2 (Analyze) delegates to `/project-context` and handles empty repo detection
- [ ] Phase 3 (Interview) presents codebase findings for confirm-or-correct and uses AskUserQuestion throughout
- [ ] Phase 3 switches to interview-heavy mode when empty repo is detected
- [ ] Phase 3 Guardrails domain offers stack-specific hook presets via multiSelect
- [ ] Phase 4 (CLAUDE.md) delegates to `/generate-claude-md` with interview context
- [ ] Phase 5 (Hooks) generates protection hooks directly with patterns from interview
- [ ] Failed skill delegations are skipped with logged reasons (skip-and-report)
- [ ] Wrap-up presents summary of all phases and offers to commit via `/commit`
- [ ] Skill provides clear explanations at each step for team-facing usability

---

## Phase 3: Build Validation and Preset Rebuild

**User stories**: (infrastructure — supports all user stories)

### What to build

Rebuild all 5 presets on the feature branch to include the new core skills. Run smoke tests to verify the built plugins have correct structure, all skill files are present, and reference files are bundled. This validates that the build system correctly picks up the new skills without manifest changes. The rebuilt dist/ is committed on the feature branch so the MR includes the full output.

### Acceptance criteria

- [ ] All 5 presets rebuild successfully with `uv run python -m scripts.build_preset <preset>`
- [ ] Smoke tests pass for all 5 presets with `uv run python -m scripts.smoke_test <preset>`
- [ ] Built plugins include `skills/generate-claude-md/SKILL.md`
- [ ] Built plugins include `skills/init-project/SKILL.md` with both reference files
- [ ] No regression in existing skill inclusion or agent configuration

---

## CEO Review Findings (2026-04-03, HOLD SCOPE)

| # | Issue | Decision | Impact |
|---|-------|----------|--------|
| 1 | Phases 2+4 (Analyze and project.md) were redundant | Merged into single Analyze phase | Pipeline reduced from 6 to 5 phases |
| 2 | No distinction between expected state transitions and actual failures | Added failure vs. state-transition table | Prevents false skip reports in wrap-up summary |
| 3 | Context passing shape between orchestrator and /generate-claude-md undefined | Defined dual-path context detection in SKILL.md preamble | Clear standalone vs. orchestrated behavior |
| 4 | Acceptance criteria mixed outcomes with process details | Kept all 13 as implementer checklist | No plan change |
| 5 | Preset rebuild timing relative to MR unclear | Rebuild on feature branch before MR | dist/ included in MR for reviewer visibility |
