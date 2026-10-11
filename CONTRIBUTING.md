# Contributing to SatyaSetu

Thank you for your interest in contributing to **SatyaSetu**! This guide outlines our development workflow, coding standards, and testing conventions.

## Code of Conduct

All contributors are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/shreyaaspires-cloud/SatyaSetu.git
   cd SatyaSetu
   ```

2. **Set up Virtual Environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Development Standards

- **Python Style**: Strict adherence to PEP 8 and modern Python 3.10+ type hinting.
- **Security & Privacy**:
  - Never commit API keys or credentials.
  - Never commit real individual identities or unverified personal data into the claim bank.
  - Adhere to OWASP recommendations: sanitize all input, validate lengths, and use HMAC-SHA256 for sender hashing.
- **Frontend**:
  - Modular native ES modules in `web/whatsapp/js/`.
  - Tokenized vanilla CSS in `web/whatsapp/css/`.
  - Zero external CDN dependencies; all assets must run offline.

## Running Tests

All pull requests must pass the automated test suite without regressions:

```bash
pytest -q
```

Ensure all tests pass before opening a Pull Request.

## Pull Request Guidelines

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Commit your changes with descriptive, conventional commit messages (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).
3. Ensure the test suite passes and working tree is clean.
4. Submit a Pull Request targeting `main`.
