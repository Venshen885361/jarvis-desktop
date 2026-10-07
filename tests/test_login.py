"""登入 / 設定檔：金鑰存哪、存了之後同一個程序裡的 settings 會不會立刻生效。"""
import os

import pytest

os.environ.setdefault("JARVIS_AGENT_TOKEN", "test")

from jarvis import config, envfile, login  # noqa: E402


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """把 .env 的候選路徑全部指到 tmp：專案的 .env 不存在、使用者的在 tmp/home/.jarvis/.env。"""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setattr(config, "env_candidates", lambda: [str(proj / ".env"), str(home / ".jarvis" / ".env")])
    monkeypatch.setattr(envfile, "user_env_path", lambda: home / ".jarvis" / ".env")
    monkeypatch.setattr(envfile, "project_root", lambda: proj)
    for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "JARVIS_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    config.reload()
    return home, proj


def test_needs_login_when_no_key(isolated_env):
    assert login.needs_login()


def test_save_writes_user_env_and_reloads_settings(isolated_env):
    home, _ = isolated_env
    path = login.save("gemini", "AIza-test-key-1234")
    assert path == home / ".jarvis" / ".env"
    text = path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIza-test-key-1234" in text and "JARVIS_PROVIDER=gemini" in text
    # 同一個程序裡的 settings 要立刻看到（不用重開）
    assert config.settings.provider == "gemini" and config.settings.gemini_api_key == "AIza-test-key-1234"
    assert not login.needs_login()


def test_project_env_writable_wins_over_user_env(isolated_env):
    home, proj = isolated_env
    (proj / ".env").write_text("JARVIS_PROVIDER=claude\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    path = login.save("claude", "sk-ant-test", "wrkspc_123")
    assert path == proj / ".env"
    text = path.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-test" in text and "ANTHROPIC_WORKSPACE_ID=wrkspc_123" in text
    assert not (home / ".jarvis" / ".env").exists()


def test_empty_project_value_does_not_shadow_user_env(isolated_env, monkeypatch):
    home, proj = isolated_env
    (proj / ".env").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    (home / ".jarvis").mkdir()
    (home / ".jarvis" / ".env").write_text("GEMINI_API_KEY=from-user\n", encoding="utf-8")
    config._load_env_files()
    assert os.environ.get("GEMINI_API_KEY") == "from-user"


def test_validate_rejects_obviously_bad_input():
    assert login.validate("gemini", "") is not None
    assert "空白" in login.validate("gemini", "abc def")


def test_agent_token_not_editable_from_login(isolated_env):
    login.save("gemini", "k")
    assert "JARVIS_AGENT_TOKEN" not in envfile.EDITABLE
