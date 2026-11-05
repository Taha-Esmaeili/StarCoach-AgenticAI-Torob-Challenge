---
name: speckit-teamwork
description: >-
  Use this skill when planning, updating specifications, breaking down tasks,
  or coordinating subagents (/teamwork) across `specs/001-torob-shopping-assistant/`
  and `ROADMAP.md`. Enforces strict alignment between SpecKit artifacts,
  `/git-workflow` atomic single-purpose branches, `/ponytail` minimal-diff
  discipline, and `/deep-interview` user verification gates.
---

# SpecKit & Multi-Agent Teamwork Protocol

## 1. SpecKit Artifact Hierarchy (`specs/001-torob-shopping-assistant/`)
All engineering work is driven by five synchronized documents plus `ROADMAP.md`:
1. `constitution.md` — Non-negotiable engineering principles (`/ponytail`, `/git-workflow`, `/deep-interview`, 300-point rubric focus).
2. `spec.md` — Product specification covering the 4 user stages, 5 pain points, UI/UX transparency rules, and RecSys requirements.
3. `plan.md` — Technical architecture (FastAPI + PostgreSQL + `pgvector` + Redis + TypeSafe `Jev` / OpenAI-compatible SDK + React 19 Vite RTL + Leaflet).
4. `data-model.md` & `contracts.md` — Exact schemas over `dataset/*.csv` and JSON API contracts between FastAPI and Next.js generative UI widgets.
5. `tasks.md` — Ordered, atomic execution tasks where each task maps 1:1 to a single-purpose `/git-workflow` branch (`feature/<task-slug>`).

## 2. Consultant & User-Verification Gate (`/deep-interview`)
- **Never guess or silently lock in product/architecture decisions.**
- Present options clearly with a `(Recommended)` choice, explain trade-offs in 1–2 lines, and wait for user approval before modifying specs or executing code.

## 3. Multi-Agent Teamwork Coordination (`/teamwork`)
When invoking subagents (`invoke_subagent`) to execute or research tasks from `tasks.md`:
1. **Single Responsibility per Subagent**: Assign each subagent a bounded scope matching one SpecKit section or one atomic task.
2. **Mandatory Context Injection**: Instruct every subagent to read `AGENTS.md` and the relevant skill (`torob-dataset-guard`, `beyond-chat-rtl-ux`, `git-workflow`, `ponytail`) before acting.
3. **Git Gate Compliance**: Subagents must **never** run `git commit`, `git push`, or create PRs autonomously. All Git mutations return to the lead agent to present Gate 1 / Gate 2 / Gate 3 to the user.

## 4. Ponytail Check on Every Task (`/ponytail`)
- Every spec section and subtask must justify its existence against the 300-point judging rubric.
- End every task report with the mandatory 1–2 line Ponytail footer:
  - **Skipped / Deferred**: What was intentionally omitted or left out of scope.
  - **Risk**: Any operational, data, or scoring risk the user must know.
