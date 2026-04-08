"""Verify PROBE_* constants are defined with the expected default values."""
from scripts.Joystick.core import config


def test_probe_constants_exist_with_defaults():
    assert config.PROBE_BASELINE_PCT == 0.3
    assert config.PROBE_STEP_PCT == 1.0
    assert config.PROBE_MAX_IMPACT_PCT == 10.0
    assert config.PROBE_RESPONSE_WINDOW_BLOCKS == 5
    assert config.PROBE_FAILURE_THRESHOLD == 2
    assert config.PROBE_CAPPED_AUTO_RESET_BLOCKS == 3
    assert config.PROBE_CAP_LOOP_WARN_THRESHOLD == 5
    assert config.PROBE_CAP_LOOP_PAUSE_THRESHOLD == 10
    assert config.PROBE_CAP_LOOP_PAUSE_BLOCKS == 30
    assert config.PROBE_LP_ADD_RETRY_LIMIT == 3
