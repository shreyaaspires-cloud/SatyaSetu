# SatyaSetu Architecture and Design Decisions (ADR)

## ADR-001: fasttext-wheel for Windows Distribution
- **Status:** Accepted
- **Context:** Standard `fasttext` package requires C++ build tools on Windows and frequently fails to compile during standard pip installation.
- **Decision:** Use `fasttext-wheel` which provides pre-compiled binaries for Windows x86_64 and CPython 3.11/3.12.
- **Consequences:** Eliminates MSVC compilation errors on Windows while preserving complete compatibility with the official fastText API.

## ADR-002: Web Search Provider Selection
- **Status:** Proposed
- **Context:** Bing Search API was retired in August 2025. SatyaSetu requires a fresh web search provider for Tier 3 retrieval.
- **Decision:** Support Brave Search API and Tavily Search API behind a unified Retriever protocol, configured via `SEARCH_PROVIDER` and `SEARCH_API_KEY`. Default set to Brave.
- **Consequences:** Search provider can be switched without modifying retrieval logic.

## ADR-003: Default Verdict on Conflicting Sources
- **Status:** Accepted
- **Context:** When reliable sources offer contradictory assessments of a viral claim, declaring a binary TRUE or FALSE would mislead users.
- **Decision:** Set default verdict to `UNVERIFIABLE` with explicit notes detailing the conflicting evidence.
- **Consequences:** Reduces false certainty and protects credibility before judges and end-users.

## ADR-004: Native Speaker Label Review
- **Status:** Accepted
- **Context:** Machine translations of nuance-heavy WhatsApp claims across Hindi, Marathi, Tamil, Telugu, and Bengali can introduce semantic shifts.
- **Decision:** Verification labels and template phrases must undergo review by native speakers prior to final live demonstration.
- **Consequences:** Prevents awkward or misleading regional phrasing in WhatsApp replies.

## ADR-005: NLI Model Latency Measurement
- **Status:** Accepted
- **Context:** Cross-encoder NLI models (such as `roberta-large-mnli`) provide high accuracy for stance detection but may introduce latency on CPU.
- **Decision:** Benchmark inference latency on target hardware before finalizing default NLI model size; allow fallback to lighter models if budget exceeded.
- **Consequences:** Keeps end-to-end processing within the 8000ms retrieval and verification budget.

## ADR-006: Hinglish Handling Strategy
- **Status:** Accepted
- **Context:** M2M100 exhibits degraded translation quality on romanized Hindi (Hinglish) forwards.
- **Decision:** Detect Hinglish (Latin script with Hindi vocabulary) and route through Gemini Flash with strict JSON schema fallback rather than M2M100.
- **Consequences:** Preserves colloquial context and colloquial idioms in viral forwards.

## ADR-007: Neutral Fact-Checking Language
- **Status:** Accepted
- **Context:** Calling claims "fake" or "lies" triggers defensive bias in forwarded message recipients.
- **Decision:** Use neutral, evidence-grounded verdicts (SUPPORTED, REFUTED, MISLEADING, UNVERIFIABLE) and cite verified sources directly without accusatory terminology.
- **Consequences:** Fosters trust and aligns with International Fact-Checking Network (IFCN) standards.

## ADR-008: Gemini SDK Package Specification
- **Status:** Accepted
- **Context:** Google has migrated the Python Gemini SDK from legacy `google-generativeai` to the unified `google-genai` SDK.
- **Decision:** Use `google-genai>=1.0.0` for all Gemini interactions, verified via Context7 and PyPI dry-run.
- **Consequences:** Uses the modern Google GenAI client structure and official typing support.
