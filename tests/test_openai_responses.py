"""Responses wire format, failures, and mixed decision/vision model routing."""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from models.execution import execution_scope
from models.llm.api.client import ApiLLMClient, ApiLLMError
from mvagent.configs import MVAgentConfig
from mvagent.configs.model_config import ApiLLMConfig
from mvagent.engine import MVAgentEngine


SCHEMA = {"type": "object", "required": ["ok"], "additionalProperties": False,
          "properties": {"ok": {"type": "boolean"}}}


def response(text='{"ok":true}', **changes):
    return {"id": "response-test", "model": "gpt-6-sol", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
                      "input_tokens_details": {"cached_tokens": 4}}, **changes}


class ResponsesTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ApiLLMConfig(provider="openai_responses", model_name="gpt-6-sol",
                                api_key="test-secret", reasoning_effort="none",
                                temperature=0, top_p=1, max_tokens=2048, max_retries=0,
                                http_headers={"x-test-route": "test"})

    def test_request_json_validation_and_credential_free_events(self):
        events = []
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(response()).encode())) as call, \
             execution_scope(emit=events.append):
            result = ApiLLMClient(self.cfg).json_chat(
                [{"role": "user", "content": "Confirm readiness."}], json_schema=SCHEMA)
        self.assertEqual(result["value"], {"ok": True})
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        payload = json.loads(request.data)
        self.assertEqual(payload["reasoning"], {"effort": "none"})
        self.assertEqual(payload["text"]["format"], {"type": "json_object"})
        self.assertFalse(payload["store"])
        self.assertEqual(payload["max_output_tokens"], 2048)
        self.assertIn("JSON Schema", payload["input"][0]["content"])
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertNotIn("test-secret", json.dumps(events))
        self.assertNotIn("x-test-route", json.dumps(events))
        usage = next(e["usage"] for e in events if e["kind"] == "model_response")
        self.assertEqual(usage["prompt_tokens"], 20)
        self.assertEqual(usage["completion_tokens"], 5)
        self.assertEqual(usage["input_tokens_details"], usage["prompt_tokens_details"])

    def test_reasoning_omits_sampling(self):
        self.cfg.reasoning_effort = "high"
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(response()).encode())) as call:
            ApiLLMClient(self.cfg).chat([{"role": "user", "content": "Hello"}])
        payload = json.loads(call.call_args.args[0].data)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("top_p", payload)

    def test_config_validates_responses_settings(self):
        from mvagent.configs.agent_config import Agent_Model_Config
        from mvagent.configs.model_config import ApiLLMModelInstanceConfig
        cfg = ApiLLMModelInstanceConfig(provider="openai_responses", model_name="gpt-6-sol",
                                        api_key="test-secret", reasoning_effort="high",
                                        http_headers={"x-test-route": "test"})
        cfg.validate("test", known_api_llm_providers=["openai_responses"])
        self.assertEqual(cfg.to_runtime_config("test", Agent_Model_Config()).http_headers,
                         {"x-test-route": "test"})
        for headers in ({"Authorization": "secret"}, {"x-test": "a\nb"}, {"x-test": 42}, None):
            cfg.http_headers = headers
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                cfg.validate("test", known_api_llm_providers=["openai_responses"])

    def test_refusal_incomplete_empty_and_malformed_are_errors(self):
        cases = [response(status="incomplete"), response(text=""),
                 response(output=[{"type": "message", "content": [{"type": "refusal"}]}]),
                 response(output=None), {}, []]
        for data in cases:
            with self.subTest(data=data), \
                 patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(data).encode())), \
                 self.assertRaises(ApiLLMError):
                ApiLLMClient(self.cfg).chat([{"role": "user", "content": "Hello"}])

    def test_http_errors_redact_secrets_and_mark_retryability(self):
        for status in (401, 429, 503):
            error = HTTPError("https://example.test", status, "error", {}, BytesIO(b"test-secret"))
            with patch("urllib.request.urlopen", side_effect=error), self.assertRaises(ApiLLMError) as caught:
                ApiLLMClient(self.cfg).chat([{"role": "user", "content": "Hello"}])
            self.assertNotIn("test-secret", str(caught.exception))
            self.assertEqual(caught.exception.transient, status != 401)

    def test_full_schema_rejects_valid_json_with_wrong_fields(self):
        bodies = [BytesIO(json.dumps(response('{"wrong":true}')).encode()) for _ in range(2)]
        with patch("urllib.request.urlopen", side_effect=bodies):
            result = ApiLLMClient(self.cfg).json_chat(
                [{"role": "user", "content": "Confirm readiness."}], json_schema=SCHEMA)
        self.assertEqual(result["status"], "invalid")

    def test_mixed_config_reaches_actual_engine_roles(self):
        import tempfile
        with patch.dict("os.environ", {"MVAGENT_DECISION_API_KEY": "test-secret"}):
            cfg = MVAgentConfig.from_yaml("configs/inference/gpt6_sol_qwen35_27b.yaml")
        decision, vision = object(), object()
        with tempfile.TemporaryDirectory() as directory:
            cfg.runtime.cache_dir = directory
            video = Path(directory) / "clip.mp4"
            video.touch()
            engine = MVAgentEngine(cfg, logger=lambda message: None)
            engine.resources._model_builder = lambda ref: decision if ref.model_type == "gpt6_sol" else vision
            with patch("mvagent.engine.probe_video_info", return_value={"duration_sec": 2, "fps": 1, "frame_count": 2}), \
                 patch("mvagent.engine.GlobalAgent", side_effect=lambda **kw: SimpleNamespace(**kw)), \
                 patch("mvagent.engine.VideoAgent", side_effect=lambda **kw: SimpleNamespace(**kw)):
                global_agent, videos = engine._preprocess(
                    videos={"video_1": str(video)}, question="Compare.",
                    output_dir=str(Path(directory) / "output"))
            self.assertIs(global_agent.model, decision)
            self.assertIs(global_agent.visual_model, vision)
            self.assertIs(videos["video_1"].planner_model, decision)
            self.assertIs(videos["video_1"].observer_model, vision)
            engine.close()


if __name__ == "__main__":
    unittest.main()
