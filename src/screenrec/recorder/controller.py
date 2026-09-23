"""Recording state machine, decoupled from any specific backend or GUI toolkit."""

from __future__ import annotations

from enum import Enum


class State(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    ERROR = "error"


class Event(Enum):
    START_REQUESTED = "start_requested"
    BACKEND_STARTED = "backend_started"
    STOP_REQUESTED = "stop_requested"
    BACKEND_STOPPED = "backend_stopped"
    FINALIZE_DONE = "finalize_done"
    BACKEND_FAILED = "backend_failed"
    RESET = "reset"


_TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.IDLE, Event.START_REQUESTED): State.STARTING,
    (State.STARTING, Event.BACKEND_STARTED): State.RECORDING,
    (State.STARTING, Event.BACKEND_FAILED): State.ERROR,
    (State.RECORDING, Event.STOP_REQUESTED): State.STOPPING,
    (State.RECORDING, Event.BACKEND_FAILED): State.ERROR,
    (State.STOPPING, Event.BACKEND_STOPPED): State.FINALIZING,
    (State.FINALIZING, Event.FINALIZE_DONE): State.IDLE,
    (State.ERROR, Event.RESET): State.IDLE,
}


class InvalidTransitionError(Exception):
    def __init__(self, state: State, event: Event):
        super().__init__(f"cannot handle {event.value} while in {state.value}")
        self.state = state
        self.event = event


def next_state(current: State, event: Event) -> State:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError:
        raise InvalidTransitionError(current, event) from None


class RecordingController:
    """Thin stateful wrapper around the pure transition table."""

    def __init__(self) -> None:
        self.state = State.IDLE

    def handle(self, event: Event) -> State:
        self.state = next_state(self.state, event)
        return self.state
