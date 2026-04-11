
# Agent Guide: Best Lines Execution Platform
# Event-Driven, AI-Assisted Market System (Codex Execution Plan)

---

## Purpose

Build a product-grade, backend-first sports market execution system that determines:

- Whether a target betting price is currently fillable
- The best available execution across sportsbooks
- The nearest miss if not fillable
- Market opportunities and monitoring signals
- Optional AI-assisted explanations and action suggestions

This project is designed to:
1. Demonstrate strong backend and systems engineering signal
2. Align with real-world sports market infrastructure systems

This system is not:
- a UI-heavy betting app
- a script or notebook project
- a full exchange or order book

This system is:
- a deterministic, market-aware execution and monitoring platform

---

## Product Definition

A user expresses intent such as:

- "Knicks moneyline +120 or better"
- "Over 221.5 at -110 or better"
- "Alert me when Celtics spread becomes -105 or better"

The system must:

1. Parse or receive structured intent
2. Retrieve latest quotes across sportsbooks
3. Match quotes to the requested market
4. Determine fillability
5. Rank best execution
6. Return nearest miss if not fillable
7. Persist latest and historical quote state
8. Emit domain events for all important outcomes
9. Support monitoring via watch intents
10. Optionally generate AI explanations and action suggestions

---

## Core Principles

### Best-Line Optimization
The backbone of the system is cross-book comparison using latest quotes.

### Deterministic Core
All core decisions must be deterministic and testable:
- quote matching
- odds comparison
- fillability
- ranking
- nearest miss
- monitoring triggers

### Event-Driven Design
The system must be event-driven in design, even if implemented synchronously at first.

### AI as Decision Support
AI is optional and layered on top:
- allowed: parsing, explanation, suggestions
- disallowed: pricing decisions, fillability, ranking

### Controlled Iteration
Build in small, testable stages without overengineering.

---

## Architecture

### Dependency Direction

api → application → domain  
application → infrastructure (via ports)

### Layers

- Domain: entities, value objects, events, policies
- Application: workflows, services, orchestration
- Infrastructure: database, providers, messaging, AI
- API: request/response and routing

---

## Domain Model

Core entities:

- Event
- Market
- Quote
- OrderIntent
- WatchIntent
- ExecutionRecommendation
- OpportunitySignal
- MarketSnapshot

---

## Deterministic Engines

- normalization_engine
- quote_matching_engine
- price_comparison_engine
- recommendation_engine
- watch_evaluation_engine
- opportunity_engine

---

## Event Model

Events must be explicitly defined and emitted:

- QuotesRefreshed
- QuoteUpdated
- MarketSnapshotCreated
- OrderIntentSubmitted
- ExecutionRecommendationGenerated
- WatchIntentSubmitted
- TargetPriceBecameFillable
- TargetPriceStillUnfilled
- MarketMovedAwayFromTarget
- OpportunityDetected
- AIExplanationGenerated

---

## Project Structure

backend/
  app/
    main.py
    config.py
    api/
    domain/
    application/
    engines/
    infrastructure/
  tests/

---

## Storage Strategy

Use Postgres.

Tables:

- events
- markets
- market_quotes_latest
- market_quotes_history
- order_intents
- watch_intents
- execution_recommendations
- workflow_events
- opportunity_signals

Latest-state drives recommendations.
History supports audit and future features.

---

## API Endpoints

Core:

- POST /execution/recommendation
- GET /events
- GET /events/{event_id}/markets
- GET /events/{event_id}/quotes

Monitoring:

- POST /watch-intents
- GET /watch-intents
- GET /opportunities

AI (later):

- POST /ai/parse-intent
- POST /ai/explain
- POST /ai/suggest-actions

---

## Core Workflows

Recommendation Flow:

Intent → Match Quotes → Compare Prices → Rank → Return Result → Emit Event

Monitoring Flow:

Quote Update → Evaluate Watch → Detect Fillability → Emit Event

Opportunity Flow:

Quote Update → Detect Improvement → Emit Opportunity

---

## Dependency Management

- Use constructor injection
- Define interfaces in application/ports
- Implement adapters in infrastructure
- Use FastAPI dependencies only at API boundary

Avoid:
- hidden wiring
- heavy DI frameworks

---

## Testing Requirements

Unit Tests:
- quote matching
- odds comparison
- ranking
- nearest miss
- monitoring logic

Integration Tests:
- recommendation endpoint
- DB-backed flows

Workflow Tests:
- quote update → opportunity
- watch intent → fillability event

---

## Development Plan

---

### Stage 0: Foundation

Step 0.1:
- Setup FastAPI
- Setup uv
- Setup Docker + Postgres

Step 0.2:
- Configure linting, typing, pytest

Step 0.3:
- Create base structure and README

Deliverable:
- runnable backend with DB and tests

---

### Stage 1: Deterministic Core (No DB)

Step 1.1:
- Define domain models

Step 1.2:
- Implement engines:
  - quote matching
  - price comparison
  - recommendation

Step 1.3:
- Implement recommendation service

Step 1.4:
- Add API endpoint

Step 1.5:
- Add unit tests

Deliverable:
- full recommendation flow using mock data

---

### Stage 2: Persistence Layer

Step 2.1:
- Define schema

Step 2.2:
- Implement repositories

Step 2.3:
- Integrate DB into recommendation flow

Step 2.4:
- Add integration tests

Deliverable:
- DB-backed system with latest and history separation

---

### Stage 3: Event Layer

Step 3.1:
- Define event classes

Step 3.2:
- Create publisher interface

Step 3.3:
- Implement in-memory/log publisher

Step 3.4:
- Emit events in workflows

Deliverable:
- event-driven architecture boundary established

---

### Stage 4: Quote Ingestion

Step 4.1:
- Define provider interface

Step 4.2:
- Implement mock provider

Step 4.3:
- Normalize incoming data

Step 4.4:
- Update latest and history tables

Deliverable:
- ingestion pipeline working

---

### Stage 5: Monitoring and Opportunities

Step 5.1:
- Define WatchIntent

Step 5.2:
- Implement watch evaluation engine

Step 5.3:
- Implement opportunity engine

Step 5.4:
- Add monitoring endpoints

Deliverable:
- system supports monitoring and alerts

---

### Stage 6: AI Layer

Step 6.1:
- Implement intent parsing

Step 6.2:
- Implement explanation generation

Step 6.3:
- Implement action suggestions

Deliverable:
- AI enhances UX without affecting deterministic core

---

### Stage 7: API Expansion

Step 7.1:
- Add read endpoints

Step 7.2:
- Improve response structure

Deliverable:
- product-ready API surface

---

### Stage 8: Observability

Step 8.1:
- Add structured logging

Step 8.2:
- Add audit trail

Deliverable:
- system is inspectable and debuggable

---

### Stage 9: Future Enhancements

- WebSockets
- Redis cache
- Event bus
- Go ingestion service
- Backtesting engine

---

## Code Quality Standards

- use type hints
- keep functions small
- keep domain pure
- keep API thin
- keep logic deterministic
- write clear tests

---

## Anti-Goals

Do NOT:
- overbuild frontend
- add microservices early
- add unnecessary infrastructure
- replace logic with AI
- expand into social features

---

## Deliverable Standard

The repository must include:

- clean architecture
- working backend
- passing tests
- documentation
- clear system explanation

---

## Final Guidance

- prioritize system behavior over language
- build in stages
- keep logic deterministic
- design for evolution
- optimize for signal, not perfection
