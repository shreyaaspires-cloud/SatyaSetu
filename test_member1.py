"""
test_member1.py
────────────────
Test file to verify Member 1's preprocessing pipeline works correctly.

Run from backend/ directory:
    python test_member1.py

Or with pytest:
    pytest test_member1.py -v
"""

import sys
import os

# Add backend/ to path so imports resolve when running directly
sys.path.insert(0, os.path.dirname(__file__))

import requests

BASE_URL = "http://localhost:8000"


def test_health():
    """Test 1 — Health check endpoint."""
    print("\n── Test 1: Health Check ──")
    try:
        res = requests.get(f"{BASE_URL}/health", timeout=5)
        data = res.json()
        print(f"Status: {res.status_code}")
        print(f"Response: {data}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert data["status"] == "ok", f"Expected 'ok', got {data['status']}"
        print("✅ Health check PASSED")
        return True
    except requests.ConnectionError:
        print("❌ Cannot connect to server — is it running? Run: uvicorn main:app --reload")
        return False
    except Exception as exc:
        print(f"❌ Health check FAILED: {exc}")
        return False


def test_text_preprocessing():
    """Test 2 — Text input preprocessing (no server needed)."""
    print("\n── Test 2: Text Preprocessing (Direct Function Call) ──")
    try:
        # Load models at module level (as lifespan would do)
        from services.input.ocr_service import load_ocr_reader
        from services.input.asr_service import load_whisper_model
        from pipelines.verify_pipeline import run_preprocessing

        print("Note: Skipping model load for text-only test...")

        result = run_preprocessing(
            body="Drinking lemon water cures cancer!!",
            media_url=None,
            media_content_type=None,
            from_number="whatsapp:+919999999999",
        )

        print(f"Result: {result}")
        assert result["input_type"] == "text", f"Expected 'text', got {result['input_type']}"
        assert "cancer" in result["raw_text"].lower(), "Expected 'cancer' in raw_text"
        assert result["from_number"] != "whatsapp:+919999999999", "Phone number should be hashed!"
        assert len(result["from_number"]) == 64, "SHA-256 hash should be 64 chars"
        assert result["original_body"] == "Drinking lemon water cures cancer!!"
        print("✅ Text preprocessing PASSED")
        return True
    except Exception as exc:
        print(f"❌ Text preprocessing FAILED: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_url_detection():
    """Test 3 — URL input type detection."""
    print("\n── Test 3: URL Input Type Detection ──")
    try:
        from pipelines.verify_pipeline import _detect_input_type

        input_type = _detect_input_type(
            body="https://www.bbc.com/news/world-asia-india-123456",
            media_url=None,
            media_content_type=None,
        )
        assert input_type == "url", f"Expected 'url', got '{input_type}'"
        print(f"Detected: '{input_type}' ✅")
        return True
    except Exception as exc:
        print(f"❌ URL detection FAILED: {exc}")
        return False


def test_image_type_detection():
    """Test 4 — Screenshot/image type detection."""
    print("\n── Test 4: Image Input Type Detection ──")
    try:
        from pipelines.verify_pipeline import _detect_input_type

        for content_type in ["image/jpeg", "image/png", "image/jpg"]:
            input_type = _detect_input_type(
                body="",
                media_url="https://api.twilio.com/media/test.jpg",
                media_content_type=content_type,
            )
            assert input_type == "screenshot", f"Expected 'screenshot' for {content_type}, got '{input_type}'"
            print(f"  {content_type} → '{input_type}' ✅")
        return True
    except Exception as exc:
        print(f"❌ Image detection FAILED: {exc}")
        return False


def test_phone_hashing():
    """Test 5 — Phone number is always SHA-256 hashed."""
    print("\n── Test 5: Phone Number Hashing ──")
    try:
        from pipelines.verify_pipeline import _hash_phone
        import hashlib

        raw = "whatsapp:+919999999999"
        hashed = _hash_phone(raw)
        expected = hashlib.sha256(raw.encode()).hexdigest()

        assert hashed == expected, "Hash mismatch!"
        assert len(hashed) == 64, "SHA-256 should be 64 hex chars"
        assert raw not in hashed, "Raw phone number must not appear in hash"
        print(f"Raw: {raw}")
        print(f"Hash: {hashed[:16]}... ✅")
        return True
    except Exception as exc:
        print(f"❌ Phone hashing FAILED: {exc}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("FactGuard — Member 1 Test Suite")
    print("=" * 60)

    results = [
        test_health(),
        test_text_preprocessing(),
        test_url_detection(),
        test_image_type_detection(),
        test_phone_hashing(),
    ]

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    if passed == total:
        print("🎉 All tests PASSED!")
    else:
        print(f"⚠️  {total - passed} test(s) FAILED — review output above")
    print("=" * 60)
