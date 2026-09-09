from unittest.mock import MagicMock

from jarvis.modules.scenarios import ScenarioManager


def test_scenario_manager_crud(tmp_path):
    scenarios_file = tmp_path / "scenarios.json"
    manager = ScenarioManager(scenarios_path=str(scenarios_file))

    # Initial file created with default scenarios
    scenarios = manager.list_scenarios()
    assert "начинаем работу" in scenarios

    # Save
    data = {
        "name": "Test Scenario",
        "description": "Just testing",
        "phrases": ["тестовый режим"],
        "actions": [{"type": "speak", "text": "Тест пройден"}],
    }
    assert manager.save_scenario("test_sc", data) is True

    # Read back
    saved = manager.get_scenario("test_sc")
    assert saved is not None
    assert saved["name"] == "Test Scenario"

    # Match by key and phrase
    match1 = manager.find_matching_scenario("test_sc")
    assert match1 is not None and match1[0] == "test_sc"

    match2 = manager.find_matching_scenario("тестовый режим")
    assert match2 is not None and match2[0] == "test_sc"

    # Execution
    mock_executor = MagicMock()
    mock_speak = MagicMock()
    logs = manager.execute_scenario(saved, mock_executor, mock_speak)
    mock_speak.assert_called_once_with("Тест пройден")
    assert any("Озвучено" in log for log in logs)

    # Delete
    assert manager.delete_scenario("test_sc") is True
    assert manager.get_scenario("test_sc") is None


def test_execute_scenario_actions():
    manager = ScenarioManager()

    mock_executor = MagicMock()
    mock_executor.platform.workspace_switch.return_value = "i3-msg workspace 2"
    mock_executor.platform.volume_up.return_value = "amixer set Master 40%+"
    mock_executor._find_app_cmd.return_value = "code"

    scenario = {
        "name": "Full Test",
        "actions": [
            {"type": "workspace", "target": 2},
            {"type": "launch", "target": "vscode"},
            {"type": "volume", "amount": 40},
            {"type": "command", "target": "echo hello"},
            {"type": "speak", "text": "Все готово"},
        ],
    }

    mock_speak = MagicMock()
    logs = manager.execute_scenario(scenario, mock_executor, speak_fn=mock_speak)

    mock_executor.platform.workspace_switch.assert_called_once_with(2)
    mock_executor._find_app_cmd.assert_called_once_with("vscode")
    mock_executor.platform.volume_up.assert_called_once_with(40)
    mock_speak.assert_called_once_with("Все готово")

    run_calls = [c.args[0] for c in mock_executor._run.call_args_list]
    assert "i3-msg workspace 2" in run_calls
    assert "code" in run_calls
    assert "amixer set Master 40%+" in run_calls
    assert "echo hello" in run_calls
    assert len(logs) == 5


def test_execute_scenario_volume_down_and_negative():
    manager = ScenarioManager()

    mock_executor = MagicMock()
    mock_executor.platform.volume_down.return_value = "amixer set Master 15%-"

    scenario = {
        "name": "Volume Down Test",
        "actions": [
            {"type": "volume", "amount": -15},
            {"type": "volume", "amount": 20, "direction": "down"},
        ],
    }

    _ = manager.execute_scenario(scenario, mock_executor)
    assert mock_executor.platform.volume_down.call_count == 2
    mock_executor.platform.volume_down.assert_any_call(15)
    mock_executor.platform.volume_down.assert_any_call(20)
    mock_executor.platform.volume_up.assert_not_called()


def test_execute_scenario_volume_up_positive():
    manager = ScenarioManager()

    mock_executor = MagicMock()
    mock_executor.platform.volume_up.return_value = "amixer set Master 10%+"

    scenario = {
        "name": "Volume Up Test",
        "actions": [
            {"type": "volume", "amount": 10},
            {"type": "volume", "amount": 25, "direction": "up"},
        ],
    }

    _ = manager.execute_scenario(scenario, mock_executor)
    assert mock_executor.platform.volume_up.call_count == 2
    mock_executor.platform.volume_up.assert_any_call(10)
    mock_executor.platform.volume_up.assert_any_call(25)
    mock_executor.platform.volume_down.assert_not_called()


def test_scenario_delay_action(monkeypatch):
    manager = ScenarioManager()
    mock_sleep = MagicMock()
    monkeypatch.setattr("time.sleep", mock_sleep)

    scenario = {
        "name": "Delay Test",
        "actions": [{"type": "delay", "seconds": 2.5}],
    }
    logs = manager.execute_scenario(scenario, MagicMock())
    mock_sleep.assert_called_once_with(2.5)
    assert any("Пауза 2.5 сек" in log for log in logs)


def test_scenario_action_error_handling():
    manager = ScenarioManager()
    mock_executor = MagicMock()
    mock_executor._run.side_effect = RuntimeError("Command execution failed")

    scenario = {
        "name": "Failing Test",
        "actions": [{"type": "command", "target": "bad_cmd"}],
    }
    logs = manager.execute_scenario(scenario, mock_executor)
    assert any("Ошибка в действии command" in log for log in logs)


def test_scenario_substring_matching(tmp_path):
    scenarios_file = tmp_path / "sub_scenarios.json"
    manager = ScenarioManager(scenarios_path=str(scenarios_file))
    manager.save_scenario(
        "coding",
        {
            "name": "Coding Mode",
            "phrases": ["хочу кодить"],
            "actions": [],
        },
    )

    # Substring match on phrase
    match = manager.find_matching_scenario("быстро хочу кодить сейчас")
    assert match is not None
    assert match[0] == "coding"


def test_scenario_word_boundary_matching(tmp_path):
    scenarios_file = tmp_path / "wb_scenarios.json"
    manager = ScenarioManager(scenarios_path=str(scenarios_file))
    manager.save_scenario(
        "work",
        {
            "name": "Work",
            "phrases": ["код"],
            "actions": [],
        },
    )

    # Substrings inside longer words must NOT match
    assert manager.find_matching_scenario("купи сковородка") is None
    assert manager.find_matching_scenario("проверь network пожалуйста") is None

    # Whole words in phrase MUST match
    match1 = manager.find_matching_scenario("пиши код быстрее")
    assert match1 is not None and match1[0] == "work"

    match2 = manager.find_matching_scenario("start work now")
    assert match2 is not None and match2[0] == "work"
