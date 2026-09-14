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


def test_mutation_generate_and_reduce_smoke():
    from research.mt import mutation, reduce

    src = "import re\n_R = re.compile(r\"^(?:打開|開啟)\\s*(?!心)x?\")\nK = (\"a\", \"b\")\nif 3 <= 4 and not False:\n    pass\n"
    ms = mutation.generate(src)
    ops = {m.op for m in ms}
    assert {"ALT_DEL", "LOOK_DEL", "KW_DEL", "NUM", "CMP", "BOOL"} <= ops
    assert all(m.source != src for m in ms)
    # 縮減：3 條測試、需求 {0,1},{1},{2} → 貪婪應選 2 條且全涵蓋
    cov = [{0, 1}, {1}, {2}]
    assert set(reduce.kill_set(reduce.greedy(cov), cov)) == {0, 1, 2}
    assert len(reduce.hgs(cov)) == 2 and len(reduce.irreplaceable_first(cov)) == 2
    assert abs(reduce.apfd([0, 2, 1], cov, 3) - (1 - (1 + 1 + 2) / 9 + 1 / 6)) < 1e-9


def test_survivor_classification_is_backed_by_killers():
    """survivors_manual.json 的人工分類要有可執行證據：uncovered 的 killer 真的殺得掉、equivalent 的殺不掉。
    router.py 改過導致 id 對不上的條目跳過（要重跑突變測試再分類），不算失敗。"""
    from research.mt import survivors

    bad, stale, rows = survivors.verify(quiet=True)
    assert bad == 0, [r for r in rows if (r[1] == "uncovered") != (r[2] == "殺") and r[1] != "harness"]
    assert stale < len(rows) + stale  # 至少有一筆還對得上
