# SatyaSetu Verification Engine Evaluation Report

- **Mode:** Offline
- **Total Benchmark Claims:** 25
- **Coverage:** 56.0%
- **Precision:** 142.9%
- **Confident wrong rate:** 0.0% (target: 0% on adversarial set)
- **Latency (p50):** 0.1 ms
- **Latency (p95):** 0.6 ms

## Per-Verdict Breakdown

- **FALSE:** 10
- **OUTDATED:** 1
- **TRUE:** 3
- **UNVERIFIABLE:** 11

## Error Analysis Grouped by Cause

### Cause: Retrieval
- **Count:** 4
  - `c02`: World Health Organization declared COVID-19 as a pandemic in March 2020. (expected: TRUE)
  - `c08`: Reserve Bank of India has banned all 500 rupee currency notes starting tomorrow. (expected: FALSE)
  - `c09`: Aadhaar card is mandatory for mobile SIM connection as per supreme court ruling. (expected: PARTIALLY_SUPPORTED)
  - `c10`: Old video from 2018 showing storm damage claimed as cyclone Remal in 2024. (expected: OUTDATED)

### Cause: Language
- **Count:** 1
  - `c13`: आरबीआई ने 500 रुपये के नए नोटों पर पाबंदी लगा दी है। (expected: FALSE)

### Cause: Detail Mismatch
- **Count:** 0
  - *No errors attributed to this cause.*

### Cause: Rule
- **Count:** 0
  - *No errors attributed to this cause.*

### Cause: Model
- **Count:** 0
  - *No errors attributed to this cause.*

