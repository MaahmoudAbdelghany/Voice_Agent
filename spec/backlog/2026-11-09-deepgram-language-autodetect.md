# Backlog: Deepgram Language Auto-Detection for Egyptian Arabic & English

- **Date**: 2026-11-09
- **Raised during**: Phase 5 interview (`phase/5-livekit-voice-core`, Question 10 / Decision P11)
- **Status**: Open
- **Type**: Research

## Question / Idea
Evaluate whether Deepgram `nova-3` (or a future Deepgram model / first-turn language detector) can reliably auto-detect and switch between Egyptian Arabic (`ar`) and English (`en`) mid-call without degrading Egyptian colloquial transcription accuracy or breaking the `< 200ms` STT latency budget.

## Context
- `spec/tech.md` §1 & §2.1: Deepgram `nova-3` streaming STT with `< 200ms` interim/final transcription budget.
- `spec/features/feature-511-clinic-persona-system-prompts/requirements.md` R3.1: System prompt instructs the LLM to reply by default in polite Egyptian Arabic and mirror the caller's language.
- `spec/phases/phase-5-livekit-voice-core/phase-overview.md` Decision P11: Phase 5 sets one language per call from a room/token attribute (default `ar`), configuring STT, greeting, and system prompt together.

## Findings
- Deepgram `nova-3` `language="multi"` code-switching support does not yet cover Egyptian Arabic dialects with the same accuracy as dedicated `language="ar"`.
- Re-initializing the LiveKit `STT` stream after the first utterance introduces reconnection latency and risks dropping audio frames during the transition.

## Recommendations
| # | Recommendation | Human decision (accepted / changed / rejected) |
|:---|:---|:---|
| 1 | Keep single-language-per-call (`ar` default, `en` via SIP trunk / signed JWT attribute) for Phase 5 and benchmark Deepgram multilingual Arabic support later when upstream dialect coverage matures. | Accepted (Phase 5 Q10 / P11) |

## Next Step
Small research spike (benchmarking WER and latency on recorded Egyptian Arabic + English code-switched clinic audio) before scheduling a feature via `sdd-replan` (mode B).
