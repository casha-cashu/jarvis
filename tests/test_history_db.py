from jarvis.modules import history_db


def test_sqlite_history_crud(tmp_path):
    db_file = tmp_path / "test_history.db"

    # 1. Initial load should be empty
    hist = history_db.load_history(session_id="test_sess", db_path=db_file)
    assert hist == []

    # 2. Save history
    messages = [
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Здравствуйте, сэр"},
    ]
    history_db.save_history(messages, session_id="test_sess", db_path=db_file)

    loaded = history_db.load_history(session_id="test_sess", db_path=db_file)
    assert loaded == messages

    # 3. Append single message
    history_db.append_message(
        session_id="test_sess",
        role="user",
        content="Который час?",
        db_path=db_file,
    )
    loaded_after = history_db.load_history(session_id="test_sess", db_path=db_file)
    assert len(loaded_after) == 3
    assert loaded_after[-1]["content"] == "Который час?"

    # 4. Limit parameter
    limited = history_db.load_history(session_id="test_sess", limit=2, db_path=db_file)
    assert len(limited) == 2
    assert limited[0]["content"] == "Здравствуйте, сэр"
    assert limited[1]["content"] == "Который час?"

    # 5. List sessions
    sessions = history_db.list_sessions(db_path=db_file)
    assert len(sessions) == 1
    assert sessions[0]["id"] == "test_sess"
    assert sessions[0]["message_count"] == 3

    # 6. Delete session
    assert history_db.delete_session("test_sess", db_path=db_file) is True
    assert history_db.load_history(session_id="test_sess", db_path=db_file) == []
    assert len(history_db.list_sessions(db_path=db_file)) == 0


def test_sqlite_migration_from_json(tmp_path):
    import json

    db_file = tmp_path / "migrated.db"
    json_file = tmp_path / "legacy_history.json"
    json_file.write_text(
        json.dumps(
            [
                {"role": "user", "content": "Сохраненный вопрос"},
                {"role": "assistant", "content": "Сохраненный ответ"},
            ]
        ),
        encoding="utf-8",
    )

    conn = history_db.get_connection(db_file)
    history_db._migrate_from_json_if_needed(conn, json_file)
    conn.close()

    loaded = history_db.load_history(session_id="default", db_path=db_file)
    assert len(loaded) == 2
    assert loaded[0]["content"] == "Сохраненный вопрос"
    assert loaded[1]["content"] == "Сохраненный ответ"
