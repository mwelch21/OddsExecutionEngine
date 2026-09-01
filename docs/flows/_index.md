---
type: index
project: odds-execution-engine
tags:
  - flow
  - index
updated: 2026-08-25
---

# OddsExecutionEngine — Flow documentation

This directory contains living documentation of how data and state flow
through the system. Each flow doc describes a specific user action or system
event and traces it through every service it touches.

## How to use this

- Looking for how something works? Find the relevant flow below.
- About to modify cross-service code? Read the relevant flow doc first.
- Made a structural change? Update the flow doc in the same commit.
- Made an architectural decision? Write a decision record in `_decisions/`.

## Flows

| Flow | Description | Services | Last updated |
|---|---|---|---|
| [[quote-ingestion-refresh]] | How external quotes are fetched, normalized, and persisted | QuoteIngestionService, NormalizationEngine, QuoteIngestionUoW | 2026-08-25 |
| [[execution-recommendation]] | How an order intent is evaluated against available quotes to produce a best-execution recommendation | RecommendationService, QuoteMatchingEngine, RecommendationEngine | 2026-08-25 |

## Decision log

| Decision | Date | Affects |
|---|---|---|
| [[2026-08-25-persist-and-publish-after-commit]] | 2026-08-25 | Both flows |
| [[2026-08-25-latest-plus-history-persistence]] | 2026-08-25 | Quote ingestion |

## Service catalog

| Service | Package | Primary responsibility |
|---|---|---|
| [[QuoteIngestionService]] | `backend/app/application/quote_ingestion_service.py` | Orchestrates provider fetch → normalization → persistence → event publish |
| [[RecommendationService]] | `backend/app/application/recommendation_service.py` | Orchestrates intent persistence → quote matching → recommendation → event publish |
| [[NormalizationEngine]] | `backend/app/engines/normalization_engine.py` | Filters and validates raw provider quotes into canonical form |
| [[QuoteMatchingEngine]] | `backend/app/engines/quote_matching_engine.py` | Matches available quotes against an order intent's criteria |
| [[RecommendationEngine]] | `backend/app/engines/recommendation_engine.py` | Ranks matched quotes and determines fillability |
| [[PriceComparisonService]] | `backend/app/engines/price_comparison_engine.py` | Determines if a quoted price meets the target |
| [[InMemoryQuoteProvider]] | `backend/app/infrastructure/quote_provider.py` | Mock provider returning fixture quotes |
| [[LoggingWorkflowEventPublisher]] | `backend/app/infrastructure/publishers/logging_publisher.py` | Post-commit event publisher (logs events, no external bus yet) |

## Open issues

| Severity | Count |
|---|---|
| 🔴 Critical | 0 |
| 🟡 Moderate | 4 |
| 🟢 Low | 3 |

See individual flow docs for details.
