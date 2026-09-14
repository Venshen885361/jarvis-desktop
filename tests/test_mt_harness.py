"""研究用測試骨架（research/mt）的煙霧測試：不打 API、不碰裝置。"""
import os

os.environ.setdefault("JARVIS_AGENT_TOKEN", "test")

from research.mt import rules  # noqa: E402
from research.mt.harness import Label, route_label, same_route  # noqa: E402
from research.mt.relations import BY_ID  # noqa: E402


def test_route_label_is_pure_and_stable():
    assert route_label("打開記事本") == Label("open_application", "記事本")
    assert route_label("播晴天") == Label("youtube_play", "晴天")
    assert route_label("附近有什麼好吃的") == Label("info")
    assert route_label("今天很開心") == Label("model")
    assert route_label("把客廳燈關掉") == Label("home_control", "客廳燈=off")


def test_same_route_ignores_case_and_space():
    assert same_route(Label("open_application", "Chrome"), Label("open_application", " chrome "))
    assert not same_route(Label("open_application", "Chrome"), Label("open_url", "Chrome"))


def test_rules_generator_produces_variants_for_each_relation():
    for rid in BY_ID:
        out = rules.generate("打開記事本", BY_ID[rid], 5)
        assert out and all(o != "打開記事本" for o in out), rid
