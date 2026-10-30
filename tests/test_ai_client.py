"""Check request/response handling against the real SDK with a mocked HTTP transport."""
import json

import importlib.util

import anthropic

httpx = importlib.import_module("httpx2" if importlib.util.find_spec("httpx2") else "httpx")

from radar.ai import AI, CLIAI

PROFILE = {"me": "작가", "interested_in": ["굿즈"], "not_interested_in": ["채용"],
           "fit": {"pixel": "굿즈", "yekki": "가구"}}


def make_client(payload, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=payload)
    return anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                               max_retries=0)


def test_extract_parses_tool_use():
    seen = []
    payload = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
               "stop_reason": "tool_use", "stop_sequence": None,
               "usage": {"input_tokens": 1000, "output_tokens": 200},
               "content": [{"type": "tool_use", "id": "tu_1", "name": "record_call",
                            "input": {"is_open_call": True, "relevance": 3, "title": "굿즈 공모"}}]}
    ai = AI(PROFILE, "2026-10-30", client=make_client(payload, seen))
    rec = ai.extract({"url": "https://x.kr/1", "text": "본문", "attachments": [], "attachment_text": ""}, {"title": "t"})
    assert rec["title"] == "굿즈 공모"
    assert seen[0]["tool_choice"] == {"type": "tool", "name": "record_call"}
    assert ai.usage.input_tokens == 1000 and ai.usage.cost() > 0


def test_discover_parses_calls_block_and_counts_searches():
    seen = []
    text = '찾았어요.\n<calls>[{"title": "A 공모", "url": "https://a.kr/1", "org": "A", "deadline": "2026-11-20"}, {"title": "bad", "url": "ftp://x"}]</calls>'
    payload = {"id": "msg_2", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
               "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 5000, "output_tokens": 300, "server_tool_use": {"web_search_requests": 2}},
               "content": [{"type": "text", "text": text}]}
    ai = AI(PROFILE, "2026-10-30", client=make_client(payload, seen))
    found = ai.discover({"id": "q", "ask": "굿즈 공모"}, 3)
    assert [f["url"] for f in found] == ["https://a.kr/1"]
    assert seen[0]["tools"][0]["type"] == "web_search_20250305"
    assert ai.usage.searches == 2


def test_api_error_is_recorded_not_raised():
    def handler(request):
        return httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    client = anthropic.Anthropic(api_key="t", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                                 max_retries=0)
    ai = AI(PROFILE, "2026-10-30", client=client)
    assert ai.extract({"url": "u", "text": "t"}, {}) is None and ai.usage.errors


class FakeRun:
    def __init__(self, out):
        self.out, self.cmds = out, []

    def __call__(self, cmd, **kw):
        self.cmds.append((cmd, kw))
        class R: pass
        r = R(); r.stdout = json.dumps(self.out); r.stderr = ""; r.returncode = 0
        return r


def test_cli_extract_uses_structured_output_and_no_tools():
    fake = FakeRun({"is_error": False, "structured_output": {"is_open_call": True, "relevance": 2, "title": "X"},
                    "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.001})
    ai = CLIAI(PROFILE, "2026-10-30", runner=fake)
    rec = ai.extract({"url": "u", "text": "본문 내용"}, {"title": "t"})
    cmd, kw = fake.cmds[0]
    assert rec["title"] == "X" and "--json-schema" in cmd and "--allowedTools" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--system-prompt" in cmd
    assert "본문 내용" in kw["input"] and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert ai.usage.as_dict()["cli_cost_usd"] == 0.001


def test_cli_discover_allows_only_web_tools():
    fake = FakeRun({"is_error": False, "result": '<calls>[{"title": "A", "url": "https://a.kr"}]</calls>'})
    ai = CLIAI(PROFILE, "2026-10-30", runner=fake)
    assert ai.discover({"id": "q", "ask": "찾아줘"}, 3)[0]["url"] == "https://a.kr"
    cmd, _ = fake.cmds[0]
    assert cmd[cmd.index("--allowedTools") + 1] == "WebSearch,WebFetch"


def test_cli_error_returns_none():
    ai = CLIAI(PROFILE, "2026-10-30", runner=FakeRun({"is_error": True, "result": "Not logged in"}))
    assert ai.extract({"url": "u", "text": "t"}, {}) is None and ai.usage.errors
