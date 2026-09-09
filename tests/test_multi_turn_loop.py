"""
Regression tests for Jarvis._multi_turn_loop.
Covers:
- BACKEND-BUG-4: wake word in follow-up stripped, query processed.
- BACKEND-BUG-5: special markers (_process_special) handled in multi-turn loop.
"""

from unittest.mock import MagicMock


def test_multi_turn_wake_word_stripped_and_processed(jarvis_instance):
    j = jarvis_instance
    j._recognize = MagicMock(side_effect=["джарвис какая погода", None])
    j.process_query = MagicMock(return_value="Погода ясная")
    j._speak = MagicMock()
    j._process_special = MagicMock(return_value=None)

    j._multi_turn_loop(timeout=5, phrase_limit=5)

    j.process_query.assert_called_once_with("какая погода")
    j._speak.assert_called_once_with("Погода ясная")


def test_multi_turn_bare_wake_word_returns(jarvis_instance):
    j = jarvis_instance
    j._recognize = MagicMock(side_effect=["джарвис"])
    j.process_query = MagicMock()
    j._speak = MagicMock()

    j._multi_turn_loop(timeout=5, phrase_limit=5)

    j.process_query.assert_not_called()
    j._speak.assert_not_called()


def test_multi_turn_special_command_processed(jarvis_instance):
    j = jarvis_instance
    j._recognize = MagicMock(side_effect=["тихо"])
    j._process_special = MagicMock(return_value="Хорошо, сэр. Я замолкаю.")
    j.process_query = MagicMock()
    j._speak = MagicMock()

    j._multi_turn_loop(timeout=5, phrase_limit=5)

    j._process_special.assert_called_once_with("тихо")
    j._speak.assert_called_once_with("Хорошо, сэр. Я замолкаю.")
    j.process_query.assert_not_called()
