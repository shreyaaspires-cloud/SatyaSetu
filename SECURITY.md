# Security Policy

## Supported Versions

Security updates are applied to the active deployment branch.

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

We take the security of SatyaSetu seriously. If you discover a security vulnerability, please report it responsibly:

1. **Do not disclose the vulnerability publicly** via GitHub Issues or public pull requests.
2. Please report the issue privately to the maintainers or via repository private vulnerability reporting.
3. Include detailed steps to reproduce the vulnerability, including:
   - Specific endpoint or module affected.
   - Sample payload or request reproducing the behavior.
   - Impact assessment.

Maintainers will acknowledge receipt within 48 hours and work on an expedited patch.

## Security Practices in SatyaSetu

- **Rate Limiting**: Dual-layer rate limiting (per-IP sliding window and per-hashed sender window) to prevent denial of service and abuse.
- **SSRF Protection**: Private IP, loopback, and cloud metadata request guards on all external media fetchers.
- **PII Minimization**: End-user phone numbers are salted and hashed via HMAC-SHA256. Raw verbatim user messages are never persisted to disk.
- **Constant-Time Verification**: Administrative endpoints use `secrets.compare_digest` to mitigate timing attack vectors.
