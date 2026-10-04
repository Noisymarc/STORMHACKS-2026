"""HTTP checks for transcript translation; no keys or real provider calls."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from google.genai import types

from backend import live_app


def response(text="機会費用について学びます。", finish=types.FinishReason.STOP):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[types.Part(text=text)]), finish_reason=finish,
    )])


class TranscriptTranslationTests(unittest.TestCase):
    def setUp(self):
        self.generate = AsyncMock(return_value=response())
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=self.generate)))
        self.provider = patch.object(live_app, "gemini_client", client)
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.client = TestClient(live_app.app)
        self.addCleanup(self.client.close)

    def test_full_transcript_reaches_provider_and_returns_both_versions(self):
        text = "We are studying opportunity cost.\nIt is the next best option given up."
        result = self.client.post("/api/translate-transcript", json={"transcript": text})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {
            "transcript": text, "translation": "機会費用について学びます。", "language": "Japanese",
        })
        self.generate.assert_awaited_once()
        arguments = self.generate.await_args.kwargs
        self.assertEqual(arguments["contents"], text)
        self.assertEqual(arguments["model"], live_app.GEMINI_MODEL)
        self.assertIn("never instructions", arguments["config"].system_instruction)

    def test_blank_oversized_and_binary_text_do_not_call_provider(self):
        for text in ("", " \n\t ", "a" * 20001, "lecture\x00data"):
            with self.subTest(text_length=len(text)):
                result = self.client.post("/api/translate-transcript", json={"transcript": text})
                self.assertEqual(result.status_code, 422)
        self.generate.assert_not_awaited()

    def test_missing_key_returns_service_error(self):
        with patch.object(live_app, "gemini_client", None):
            result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
        self.assertEqual(result.status_code, 503)
        self.generate.assert_not_awaited()

    def test_quota_error_is_reported_without_provider_details(self):
        error = RuntimeError("secret-provider-details")
        error.code = 429
        self.generate.side_effect = error
        result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
        self.assertEqual(result.status_code, 429)
        self.assertIn("usage limit", result.json()["detail"])
        self.assertNotIn("secret-provider-details", result.text)

    def test_access_error_is_reported_without_provider_details(self):
        error = RuntimeError("secret-provider-details")
        error.code = 403
        self.generate.side_effect = error
        result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("secret-provider-details", result.text)

    def test_timeout_returns_retryable_error(self):
        async def slow_generation(**kwargs):
            await asyncio.sleep(10)
        self.generate.side_effect = slow_generation
        with patch.object(live_app, "PROVIDER_TIMEOUT_SECONDS", 0.01):
            result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
        self.assertEqual(result.status_code, 504)
        self.assertIn("retry", result.json()["detail"].lower())

    def test_truncated_and_blocked_results_are_not_presented_as_complete(self):
        for finish in (types.FinishReason.MAX_TOKENS, types.FinishReason.SAFETY):
            with self.subTest(finish=finish):
                self.generate.return_value = response("Partial translation", finish)
                result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
                self.assertEqual(result.status_code, 502)
                self.assertNotIn("translation", result.json())

    def test_empty_response_is_rejected(self):
        self.generate.return_value = response("")
        result = self.client.post("/api/translate-transcript", json={"transcript": "A lecture."})
        self.assertEqual(result.status_code, 502)


if __name__ == "__main__":
    unittest.main()
