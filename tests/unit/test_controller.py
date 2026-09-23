import pytest

from screenrec.recorder.controller import (
    Event,
    InvalidTransitionError,
    RecordingController,
    State,
    next_state,
)


def test_start_requested_from_idle_goes_to_starting():
    assert next_state(State.IDLE, Event.START_REQUESTED) is State.STARTING


def test_backend_started_from_starting_goes_to_recording():
    assert next_state(State.STARTING, Event.BACKEND_STARTED) is State.RECORDING


def test_backend_failed_from_recording_goes_to_error():
    assert next_state(State.RECORDING, Event.BACKEND_FAILED) is State.ERROR


def test_full_happy_path_returns_to_idle():
    controller = RecordingController()
    controller.handle(Event.START_REQUESTED)
    controller.handle(Event.BACKEND_STARTED)
    controller.handle(Event.STOP_REQUESTED)
    controller.handle(Event.BACKEND_STOPPED)
    assert controller.handle(Event.FINALIZE_DONE) is State.IDLE


def test_stop_requested_while_idle_is_invalid():
    with pytest.raises(InvalidTransitionError):
        next_state(State.IDLE, Event.STOP_REQUESTED)


def test_reset_from_error_returns_to_idle():
    assert next_state(State.ERROR, Event.RESET) is State.IDLE


def test_controller_state_unchanged_after_invalid_transition_is_rejected():
    controller = RecordingController()
    with pytest.raises(InvalidTransitionError):
        controller.handle(Event.STOP_REQUESTED)
    assert controller.state is State.IDLE
