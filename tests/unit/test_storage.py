from datetime import datetime

import pytest

from screenrec.storage import default_filename, estimate_recordable_seconds


def test_default_filename_embeds_timestamp_and_extension():
    name = default_filename(now=datetime(2026, 9, 23, 14, 30, 0))
    assert name == "screenrec_2026-09-23_143000.mkv"


def test_default_filename_uses_given_extension():
    name = default_filename(now=datetime(2026, 9, 23, 14, 30, 0), extension="mp4")
    assert name.endswith(".mp4")


def test_estimate_recordable_seconds_at_known_bitrate():
    # 8000 kbps -> 1,000,000 bytes/sec; 10,000,000 bytes free -> 10 seconds
    assert estimate_recordable_seconds(free_bytes=10_000_000, total_bitrate_kbps=8000) == 10.0


def test_estimate_recordable_seconds_rejects_non_positive_bitrate():
    with pytest.raises(ValueError, match="positive"):
        estimate_recordable_seconds(free_bytes=1000, total_bitrate_kbps=0)
