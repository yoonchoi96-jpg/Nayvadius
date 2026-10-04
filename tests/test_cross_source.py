[object Object]

def test_entity_writer_contains_documents_and_relations(tmp_path, monkeypatch):
    from nayvadius.writer import write_entities_from_db
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))
    save_result(_result("doc-a", "abraham", "Taylor Swift"))
    save_result(ProcessedDocument(
        Document("doc-b", "Second", "content", "jacques"),
        "summary",
        [Entity("Taylor Swift", "People", 0.95)],
        ["source/jacques"],
        relations=[Relation("Taylor Swift", "performed", "Example Song", 0.9)],
    ))
    with connect() as db:
        write_entities_from_db(db, tmp_path / "output")
    note = (tmp_path / "output" / "entities" / "People" / "Taylor Swift.md").read_text()
    assert "## Sources" in note
    assert "[[doc-a]]" in note
    assert "[[doc-b]]" in note
    assert "## Relations" in note
    assert "performed" in note
