# Capabilities Index

---

## What Is a Capability?

A capability is a single, discrete action or behavior the agent performs.

## Capabilities in This Project

| Capability | File |
|-----------|------|
| Dataset Ingestion | [dataset-ingestion.md](dataset-ingestion.md) |
| Conversational Data Analysis | [conversational-data-analysis.md](conversational-data-analysis.md) |
| Conversation Memory | [conversation-memory.md](conversation-memory.md) |
| Run History | [run-history.md](run-history.md) |

Phase 1 delivers a real, working baseline of all four capabilities on the primary journey (upload → ask → answer, with memory and a persisted audit trail). Phase 2 deepens Conversational Data Analysis (richer retry strategies, large-file scale), Run History (search/filter), and Conversation Memory (dataset reselect) — see `spec/roadmap.md` → Phases of Development.

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer sub-agent will:
1. Create a new file in this directory (`<name>.md`, no number prefix)
2. Update this index
3. Flag any dependencies on existing capabilities
4. Self-review that it fits the architecture and data model before returning

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Business rules** (constraints and edge-case handling)
- **Success criteria** (how we test it)
