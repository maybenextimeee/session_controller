from session_controller import registry
from session_controller.pins import initial_pins
from session_controller.settings import Settings
from session_controller.targets import AI, BROWSER, Target, WINDOWS_CREDENTIALS


def test_defaults_follow_browser_and_installed_ai(monkeypatch):
    targets = [Target("chrome", "Chrome", BROWSER), Target("edge", "Edge", BROWSER),
               Target("claude", "Claude", AI), Target("telegram", "Telegram"), WINDOWS_CREDENTIALS]
    monkeypatch.setattr(registry, "read_string", lambda *args: "MSEdgeHTM")
    assert initial_pins(targets, {"chrome", "edge", "claude"}) == [
        "edge", "claude", "windows_credentials", "telegram",
    ]


def test_unpin_all_survives_reload(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings.load(path).pinned_targets is None
    Settings(language="en", pinned_targets=[], disabled_targets=["chrome"]).save(path)
    restored = Settings.load(path)
    assert restored.pinned_targets == []
    assert restored.language == "en"
    assert restored.disabled_targets == ["chrome"]
