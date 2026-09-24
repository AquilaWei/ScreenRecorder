import pytest

pytest.importorskip("jeepney")  # Linux-only dependency

from screenrec.recorder.portal import (  # noqa: E402
    CURSOR_EMBEDDED,
    CURSOR_HIDDEN,
    choose_cursor_mode,
    first_stream_node,
    request_path,
)


def test_request_path_is_built_from_the_unique_bus_name_and_token():
    assert (
        request_path(":1.2193", "screenrec_ab")
        == "/org/freedesktop/portal/desktop/request/1_2193/screenrec_ab"
    )


def test_cursor_is_drawn_into_the_video_when_the_desktop_supports_it():
    assert choose_cursor_mode(available_modes=1 | 2) == CURSOR_EMBEDDED


def test_cursor_is_left_out_when_the_desktop_cannot_embed_it():
    assert choose_cursor_mode(available_modes=1) == CURSOR_HIDDEN


def test_first_stream_node_reads_the_node_id_from_the_start_response():
    # Shape copied from a real KDE Plasma 6 response.
    results = {
        "streams": (
            "a(ua{sv})",
            [(125, {"mapping_id": ("s", "eDP-1"), "size": ("(ii)", (1800, 1125))})],
        ),
        "restore_token": ("s", "d1stOv9a7zP2Q4DMFtr_cA"),
    }
    assert first_stream_node(results) == 125


def test_first_stream_node_fails_when_the_desktop_shares_nothing():
    with pytest.raises(RuntimeError):
        first_stream_node({"streams": ("a(ua{sv})", [])})
