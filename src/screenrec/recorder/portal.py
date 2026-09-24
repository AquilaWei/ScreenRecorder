"""Screen access on Linux through xdg-desktop-portal (ScreenCast + Inhibit).

Wayland doesn't let an app read the screen by itself: it asks the portal, the
desktop shows its own "share which screen?" dialog, and the answer is a
PipeWire stream (an fd plus a node id) that GStreamer's pipewiresrc can read.
The same D-Bus connection also holds a sleep/idle inhibition for the recording.

The connection outlives each recording on purpose - see ScreenCastPortal.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.blocking import DBusConnection, Proxy, open_dbus_connection
from jeepney.wrappers import unwrap_msg

_DESKTOP_PATH = "/org/freedesktop/portal/desktop"
_DESKTOP_BUS = "org.freedesktop.portal.Desktop"
_SCREENCAST = DBusAddress(
    _DESKTOP_PATH, bus_name=_DESKTOP_BUS, interface="org.freedesktop.portal.ScreenCast"
)
_INHIBIT = DBusAddress(
    _DESKTOP_PATH, bus_name=_DESKTOP_BUS, interface="org.freedesktop.portal.Inhibit"
)
_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
_SESSION_INTERFACE = "org.freedesktop.portal.Session"
_PROPERTIES = DBusAddress(
    _DESKTOP_PATH, bus_name=_DESKTOP_BUS, interface="org.freedesktop.DBus.Properties"
)

SOURCE_MONITOR = 1
CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2
# Remember the chosen screen while the app runs, so only the first recording asks.
PERSIST_WHILE_RUNNING = 1
INHIBIT_SUSPEND = 4
INHIBIT_IDLE = 8

RESPONSE_OK = 0
RESPONSE_CANCELLED = 1

# Quick portal calls answer at once; Start waits for the user to pick a screen.
_CALL_TIMEOUT_SEC = 30
_USER_CHOICE_TIMEOUT_SEC = 300


class PortalCancelledError(Exception):
    """The user closed the portal's screen-sharing dialog without choosing."""


@dataclass(frozen=True)
class ScreenStream:
    fd: int  # PipeWire remote; owned by ScreenCastPortal, closed by end_cast()
    node_id: int


def request_path(unique_name: str, token: str) -> str:
    """Object path the portal will use for a request made with `token`.

    Known in advance so the Response signal can be subscribed to before the
    call - otherwise a fast portal could answer before we listen.
    """
    sender = unique_name.lstrip(":").replace(".", "_")
    return f"{_DESKTOP_PATH}/request/{sender}/{token}"


def choose_cursor_mode(available_modes: int) -> int:
    """Draw the cursor into the video when the desktop supports it."""
    return CURSOR_EMBEDDED if available_modes & CURSOR_EMBEDDED else CURSOR_HIDDEN


def first_stream_node(start_results: dict) -> int:
    """PipeWire node id of the first stream in the ScreenCast.Start response."""
    streams = start_results.get("streams", ("a(ua{sv})", []))[1]
    if not streams:
        raise RuntimeError("桌面沒有提供任何可錄製的螢幕")
    return streams[0][0]


class ScreenCastPortal:
    """The app's line to the desktop's screen-cast portal: shares a screen for
    each recording (`start_cast()` .. `end_cast()`) over one D-Bus connection.

    Keep one instance for the app's lifetime: the portal remembers the chosen
    screen (PERSIST_WHILE_RUNNING) only for the connection that chose it, and
    forgets it when that connection closes - a connection per recording
    brought the "which screen?" dialog back every time (found live on KDE).

    Blocking, including a wait of up to several minutes for the user's choice
    in the desktop's dialog - call from a worker thread, never the GUI thread.
    """

    def __init__(self) -> None:
        self._conn: DBusConnection | None = None
        self._session_handle: str | None = None  # while a screen is shared
        self._inhibit_handle: str | None = None
        self._stream: ScreenStream | None = None
        # Hands the previous choice to the next start_cast(); the portal issues
        # a new token each time.
        self.restore_token: str | None = None

    def start_cast(self) -> ScreenStream:
        """Ask for a screen - without a dialog if the desktop still remembers
        the last choice. Raises PortalCancelledError if the user declines,
        RuntimeError if the portal fails, and jeepney/OS errors if there's no
        session bus or no portal at all."""
        if self._conn is None:
            self._conn = open_dbus_connection(bus="SESSION", enable_fds=True)
        try:
            session = self._request(
                "CreateSession", "a{sv}", (), {"session_handle_token": ("s", _new_token())}
            )["session_handle"][1]
            self._session_handle = session
            select_options = {
                "types": ("u", SOURCE_MONITOR),
                "multiple": ("b", False),
                "cursor_mode": ("u", choose_cursor_mode(self._cursor_modes())),
                "persist_mode": ("u", PERSIST_WHILE_RUNNING),
            }
            if self.restore_token:
                select_options["restore_token"] = ("s", self.restore_token)
            self._request("SelectSources", "oa{sv}", (session,), select_options)
            results = self._request(
                "Start", "osa{sv}", (session, ""), {}, timeout=_USER_CHOICE_TIMEOUT_SEC
            )
            self.restore_token = results.get("restore_token", ("s", None))[1]
            node_id = first_stream_node(results)
            (fd,) = self._call(_SCREENCAST, "OpenPipeWireRemote", "oa{sv}", (session, {}))
            self._stream = ScreenStream(fd=fd.to_raw_fd(), node_id=node_id)
        except BaseException:
            self.end_cast()
            raise
        return self._stream

    def inhibit_sleep(self, reason: str) -> None:
        """Keep the machine awake and the screen on until `end_cast()`. Must
        follow `start_cast()`. Best effort: a desktop without the Inhibit portal
        raises DBusErrorResponse and recording can go on without it.

        NOTE: unlike the ScreenCast calls, Inhibit sends no Response signal - the
        inhibition simply lasts until its request object is closed.
        """
        (self._inhibit_handle,) = self._call(
            _INHIBIT,
            "Inhibit",
            "sua{sv}",
            ("", INHIBIT_SUSPEND | INHIBIT_IDLE, {"reason": ("s", reason)}),
        )

    def end_cast(self) -> None:
        """Stop sharing the screen and release the inhibition, keeping the
        connection so the next start_cast() can skip the dialog. Safe to call
        when nothing is shared. If the portal can't be told, the connection is
        dropped instead - that ends both too, but forgets the chosen screen."""
        if self._stream is not None:
            os.close(self._stream.fd)
            self._stream = None
        to_close = [
            (self._inhibit_handle, _REQUEST_INTERFACE),
            (self._session_handle, _SESSION_INTERFACE),
        ]
        self._inhibit_handle = None
        self._session_handle = None
        try:
            for handle, interface in to_close:
                if handle is not None:
                    address = DBusAddress(handle, bus_name=_DESKTOP_BUS, interface=interface)
                    self._call(address, "Close", "", ())
        except Exception:  # noqa: BLE001 - disconnecting ends the cast as well
            self._disconnect()

    def close(self) -> None:
        """End any cast and disconnect from the portal. Safe to call twice."""
        self.end_cast()
        self._disconnect()

    def _disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _cursor_modes(self) -> int:
        (variant,) = self._call(
            _PROPERTIES, "Get", "ss", (_SCREENCAST.interface, "AvailableCursorModes")
        )
        return variant[1]

    def _call(self, address: DBusAddress, method: str, signature: str, body: tuple) -> tuple:
        """Plain method call; raises DBusErrorResponse if the portal refuses it."""
        reply = self._conn.send_and_get_reply(
            new_method_call(address, method, signature, body), timeout=_CALL_TIMEOUT_SEC
        )
        return unwrap_msg(reply)

    def _request(
        self,
        method: str,
        signature: str,
        args: tuple,
        options: dict,
        timeout: float = _CALL_TIMEOUT_SEC,
    ) -> dict:
        """Call a portal method that answers through a Request object's
        Response signal, and return the signal's results."""
        token = _new_token()
        rule = MatchRule(
            type="signal",
            interface="org.freedesktop.portal.Request",
            member="Response",
            path=request_path(self._conn.unique_name, token),
        )
        bus = Proxy(message_bus, self._conn)
        bus.AddMatch(rule)
        options = {**options, "handle_token": ("s", token)}
        try:
            with self._conn.filter(rule) as responses:
                self._call(_SCREENCAST, method, signature, (*args, options))
                response = self._conn.recv_until_filtered(responses, timeout=timeout)
        except TimeoutError:
            raise RuntimeError(f"等候桌面回應逾時（{method}，{timeout:g} 秒）") from None
        finally:
            # The connection lives on, so don't let match rules pile up on the bus.
            bus.RemoveMatch(rule)
        code, results = response.body
        if code == RESPONSE_CANCELLED:
            raise PortalCancelledError("已取消選擇要錄製的螢幕")
        if code != RESPONSE_OK:
            raise RuntimeError(f"桌面拒絕了螢幕錄製要求（{method}，代碼 {code}）")
        return results


def _new_token() -> str:
    return "screenrec_" + secrets.token_hex(8)
