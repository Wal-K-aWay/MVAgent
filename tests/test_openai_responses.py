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
from models.llm.api.providers.openai_responses import response_schema
from models.utils import validate_json_schema
from mvagent.configs import MVAgentConfig
from mvagent.configs.model_config import ApiLLMConfig
from mvagent.engine import MVAgentEngine


SCHEMA = {"type": "object", "required": ["ok"], "additionalProperties": False,
          "properties": {"ok": {"type": "boolean"}}}


def response(text='{"result":{"ok":true}}', *, format_schema=SCHEMA, **changes):
    return {"id": "response-test", "model": "gpt-6-sol", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "text": {"format": {"type": "json_schema", "strict": True, "schema": response_schema(format_schema)}},
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
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["schema"], response_schema(SCHEMA))
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

    def test_server_schema_violation_fails_without_downgrading(self):
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(response('{"result":{"wrong":true}}')).encode())) as call, \
             self.assertRaisesRegex(ApiLLMError, "violated its strict"):
            ApiLLMClient(self.cfg).json_chat(
                [{"role": "user", "content": "Confirm readiness."}], json_schema=SCHEMA)
        self.assertEqual(call.call_count, 1)

    def test_gateway_must_confirm_the_requested_strict_schema(self):
        data = response()
        data["text"] = {"format": {"type": "json_object"}}
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(data).encode())), \
             self.assertRaisesRegex(ApiLLMError, "did not confirm"):
            ApiLLMClient(self.cfg).json_chat(
                [{"role": "user", "content": "Confirm readiness."}], json_schema=SCHEMA)

    def test_action_unions_keep_action_parameters_ids_and_bounds(self):
        from mvagent.agents.global_agent.schema import build_global_decision_schema
        from mvagent.agents.video_agent.schema import build_video_action_schema
        global_schema = response_schema(build_global_decision_schema(
            ["answer", "analyze_videos", "watch_videos"], video_ids=["a", "b"],
            video_durations={"a": 3, "b": 4}))
        valid = {"reason": "Inspect.", "action": "watch_videos", "parameters": {
            "instruction": "Compare.", "videos": [{"video_id": "a", "clip": [0, 3]},
                                                    {"video_id": "b", "clip": [0, 4]}]}}
        validate_json_schema({"result": valid}, global_schema)
        for change in ({"action": "answer"}, {"reason": " "},
                       {"parameters": {"answer": "A"}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_json_schema({"result": {**valid, **change}}, global_schema)
        video_schema = response_schema(build_video_action_schema(
            ["observe", "finish"], duration_sec=3, max_ranges=2))
        action = {"action": "observe", "parameters": {"what": "Color?", "where": [[0, 3]], "fps": 1}}
        validate_json_schema({"result": action}, video_schema)
        for change in ({"where": [[0, 4]]}, {"fps": 0}, {"what": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_json_schema({"result": {**action, "parameters": {**action["parameters"], **change}}}, video_schema)

    def test_duplicate_video_check_is_retained_in_full_local_schema(self):
        from mvagent.agents.global_agent.schema import build_global_decision_schema
        schema = build_global_decision_schema(["analyze_videos"], video_ids=["a", "b"])
        requests = [{"video_id": "a", "instruction": "Inspect."}] * 2
        action = {"reason": "Inspect.", "action": "analyze_videos",
                  "parameters": {"videoagent_request": requests}}
        validate_json_schema({"result": action}, response_schema(schema))
        with self.assertRaises(ValueError):
            validate_json_schema(action, schema)
        corrected = {**action, "parameters": {"videoagent_request": requests[:1]}}
        bodies = [BytesIO(json.dumps(response(json.dumps({"result": value}), format_schema=schema)).encode())
                  for value in (action, corrected)]
        with patch("urllib.request.urlopen", side_effect=bodies):
            result = ApiLLMClient(self.cfg).json_chat(
                [{"role": "user", "content": "Inspect both videos."}], json_schema=schema)
        self.assertEqual(result["value"], corrected)

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
