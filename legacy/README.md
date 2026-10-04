# Legacy Pre-Refactoring Archive

This directory contains pre-refactoring modules and historical prototypes from Member 1 and Member 2 (Waves 1–3).

## Notice
All active production code, business logic, endpoints, contracts, and pipelines are now located in the modern `app/` package:
- `app/core/`: Configuration, security, logging, metrics, resilience.
- `app/contracts/`: Canonical request/response data models & enums.
- `app/features/`: Modular pipelines for Ingestion, NLP, Fact-Checking, Explanation, Routing.

These legacy artifacts are preserved for auditability and characterisation regression tests.
