from nayvadius.config import settings

def test_settings_has_state_path():
    assert settings.state_path.endswith(".db")
