from sara_n42.config import load_config


def test_load_config_instruments(sample_config):
    cfg = load_config(sample_config)
    assert cfg.poll_interval_seconds == 300
    assert cfg.filename_contains == "5min"
    assert cfg.ui.host == "127.0.0.1"
    assert cfg.ui.port == 8080
    assert len(cfg.instruments) == 2
    assert cfg.instruments[0].host == "192.168.4.136"


def test_matches_filename(app_config):
    assert app_config.matches_filename("abc_5min_xyz.n42")
    assert app_config.matches_filename("ABC_5MIN_XYZ.N42")
    assert not app_config.matches_filename("abc_1h_xyz.n42")
    assert not app_config.matches_filename("abc_5min_xyz.txt")
