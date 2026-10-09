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


def test_kappa():
    from research.mt.sample import kappa

    a = {"1": 1, "2": 1, "3": 0, "4": 0}
    assert kappa(a, a) == (1.0, 4)
    k, n = kappa(a, {"1": 1, "2": 0, "3": 0, "4": 1})
    assert n == 4 and abs(k) < 1e-9  # 一半同意 = 純機率


def test_subsume_dominators():
    from research.mt.subsume import analyze, kill_vectors, minimal_score

    # 3 條測試 × 4 個突變體：m0 被 t0 殺、m1 被 t0,t1 殺（被 m0 包含）、m2 跟 m0 同一群、m3 沒人殺
    matrix = [[1, 1, 1, 0], [0, 1, 0, 0], [0, 0, 0, 0]]
    kv = kill_vectors(matrix)
    assert set(kv) == {0, 1, 2}
    res = analyze(kv)
    assert res["classes"] == 2 and res["dominator_classes"] == 1
    assert minimal_score({0}, res["dominators"]) == 1.0 and minimal_score({1}, res["dominators"]) == 0.0


def test_transfer_cov_drops_trivial():
    from research.mt.transfer import cov_of

    cov, n = cov_of([[1, 1, 0], [1, 0, 0]])   # 第 0 個突變體每條測試都殺（trivial）→ 丟掉
    assert n == 1 and cov == [{0}, set()]


def test_hass_template_mutants_do_not_need_hassil():
    # 模板突變是純字串操作：不裝 hassil 也要能產生、而且數量跟分支數對得上
    from research.mt.hass_mutation import _string_mutants

    outs = _string_mutants("<open>[把|將]{name}(打開|開|開啟)[的]")
    ops = [o[0] for o in outs]
    assert ops.count("ALT_DEL") == 3          # 三個分支各刪一個
    assert ops.count("OPT_DEL") == 2          # 兩個可選群組
    assert ("ALT_DEL", "<open>[把|將]{name}(打開|開|開啟)[的]", "<open>[把|將]{name}(開|開啟)[的]") in outs
    assert any(after == "<open>(把|將){name}(打開|開|開啟)[的]" for _, _, after in outs)   # [a|b] → (a|b)
    assert all(before != after for _, before, after in outs)
