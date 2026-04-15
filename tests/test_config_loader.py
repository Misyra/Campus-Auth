from __future__ import annotations

from src.utils.config import ConfigLoader


def test_load_config_defaults_monitor_interval_and_ping_targets(monkeypatch) -> None:
    monkeypatch.setattr("src.utils.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("MONITOR_INTERVAL", raising=False)
    monkeypatch.delenv("PING_TARGETS", raising=False)
    monkeypatch.delenv("Campus-Auth_ENV_FILE", raising=False)
    monkeypatch.delenv("JCU_ENV_FILE", raising=False)

    config = ConfigLoader.load_config_from_env()

    assert config["monitor"]["interval"] == 300
    assert config["monitor"]["ping_targets"] == [
        "8.8.8.8:53",
        "114.114.114.114:53",
        "www.baidu.com:443",
    ]
