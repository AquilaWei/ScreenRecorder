"""ScreenCaptureKit (macOS 13+) through pyobjc: one SCStream delivering a
display's frames as NV12 and its system audio as 32-bit float.

Only importable on macOS. The SCK calls that complete asynchronously are
wrapped into blocking ones here, so the backend reads like the other ones.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable

import objc

# Every pyobjc name is imported here, once, rather than looked up on the
# framework module when used: the modules resolve names lazily, and two
# threads resolving the same name for the first time can make one of them fail
# with KeyError (found in testing: the capture callbacks and the writer
# threads all start using them at once).
from CoreMedia import (
    CMAudioFormatDescriptionGetStreamBasicDescription,
    CMBlockBufferCopyDataBytes,
    CMBlockBufferGetDataLength,
    CMClockGetHostTimeClock,
    CMClockGetTime,
    CMSampleBufferGetDataBuffer,
    CMSampleBufferGetFormatDescription,
    CMSampleBufferGetImageBuffer,
    CMSampleBufferGetPresentationTimeStamp,
    CMSampleBufferGetSampleAttachmentsArray,
    CMTimeGetSeconds,
    CMTimeMake,
)
from Foundation import NSObject
from Quartz import (
    CGDisplayCopyDisplayMode,
    CGDisplayModeGetPixelHeight,
    CGDisplayModeGetPixelWidth,
    CGMainDisplayID,
    CGPreflightScreenCaptureAccess,
    CGRequestScreenCaptureAccess,
    CVPixelBufferGetBaseAddressOfPlane,
    CVPixelBufferGetBytesPerRowOfPlane,
    CVPixelBufferLockBaseAddress,
    CVPixelBufferUnlockBaseAddress,
    kCGDisplayStreamYCbCrMatrix_ITU_R_709_2,
    kCVPixelBufferLock_ReadOnly,
    kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
)
from ScreenCaptureKit import (
    SCContentFilter,
    SCFrameStatusComplete,
    SCShareableContent,
    SCStream,
    SCStreamConfiguration,
    SCStreamFrameInfoStatus,
    SCStreamOutputTypeAudio,
    SCStreamOutputTypeScreen,
)

from screenrec.recorder.audio_sync import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from screenrec.recorder.macos import FrameLayout, frame_layout, interleave_f32, output_size

SCK_TIMEOUT_SEC = 10

# The capture's queue depth: frames SCK may have in flight before it drops
# some. Frames are copied out in the callback, so a small one is enough.
_QUEUE_DEPTH = 5

_kAudioFormatFlagIsNonInterleaved = 1 << 5

PERMISSION_DENIED_MESSAGE = (
    "沒有螢幕錄製權限。請到「系統設定 → 隱私權與安全性 → 螢幕錄製」"
    "開啟 ScreenRec，然後結束並重新開啟 ScreenRec"
)


def host_clock() -> float:
    """Seconds on the host clock, the clock of every ScreenCaptureKit
    timestamp. Everything compared with those timestamps must use this."""
    return CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()))


def _wait_for(start: Callable[[Callable], None], what: str):
    """Run an SCK call taking a completion handler `(result..., error)` and
    wait for it. Returns the handler's first argument unless the call only
    reports an error. Raises RuntimeError on error or timeout."""
    done = threading.Event()
    outcome: list = []

    def handler(*args) -> None:
        outcome.extend(args)
        done.set()

    start(handler)
    if not done.wait(SCK_TIMEOUT_SEC):
        raise RuntimeError(f"ScreenCaptureKit 沒有回應（{what}）")
    error = outcome[-1]
    if error is not None:
        raise RuntimeError(f"ScreenCaptureKit {what} 失敗：{error.localizedDescription()}")
    return outcome[0] if len(outcome) > 1 else None


class _StreamOutput(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
    """Receives the stream's sample buffers on SCK's own queue."""

    def initWithCapture_(self, capture):
        self = objc.super(_StreamOutput, self).init()
        if self is None:
            return None
        self._capture = capture
        return self

    def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, output_type):
        try:
            if output_type == SCStreamOutputTypeScreen:
                self._capture._on_screen_buffer(sample_buffer)
            elif output_type == SCStreamOutputTypeAudio:
                self._capture._on_audio_buffer(sample_buffer)
        except Exception as exc:  # noqa: BLE001 - an exception would kill SCK's queue
            if sys.stderr is not None:
                print(f"[screencapture] dropped a buffer: {exc!r}", file=sys.stderr)


class ScreenCapture:
    """One display's frames and system audio, reported through callbacks on
    ScreenCaptureKit's own threads:

    - `on_video(presented_at, layout, nv12_bytes)` for each new frame
    - `on_audio(presented_at, interleaved_f32_bytes)` for each audio buffer,
      or no audio capture at all when `on_audio` is None

    Times are `host_clock()` seconds.
    """

    def __init__(
        self,
        on_video: Callable[[float, FrameLayout, bytes], None],
        on_audio: Callable[[float, bytes], None] | None,
    ) -> None:
        self._on_video = on_video
        self._on_audio = on_audio
        self._stream = None
        self._output = None
        self._frame_width = 0
        self._frame_height = 0

    def start(self, display_index: int, scale_height: int | None, fps: int) -> bool:
        """Start capturing. Returns whether this app's own windows (the red
        recording indicator, the main window) are kept out of the capture.

        Raises PermissionError without the Screen Recording permission (and
        makes macOS show its prompt), RuntimeError on other failures.
        """
        if not CGPreflightScreenCaptureAccess():
            CGRequestScreenCaptureAccess()
            raise PermissionError(PERMISSION_DENIED_MESSAGE)

        content = _wait_for(
            lambda handler: (
                SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(  # noqa: E501
                    False, False, handler
                )
            ),
            "取得螢幕清單",
        )
        display = self._pick_display(content.displays(), display_index)
        own_app = [app for app in content.applications() if app.processID() == os.getpid()]
        content_filter = (
            SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(  # noqa: E501
                display, own_app, []
            )
        )

        mode = CGDisplayCopyDisplayMode(display.displayID())
        width, height = output_size(
            CGDisplayModeGetPixelWidth(mode),
            CGDisplayModeGetPixelHeight(mode),
            scale_height,
        )
        self._frame_width, self._frame_height = width, height
        self._stream = SCStream.alloc().initWithFilter_configuration_delegate_(
            content_filter, self._configuration(width, height, fps), None
        )
        self._output = _StreamOutput.alloc().initWithCapture_(self)
        self._add_output(SCStreamOutputTypeScreen)
        if self._on_audio is not None:
            self._add_output(SCStreamOutputTypeAudio)
        _wait_for(self._stream.startCaptureWithCompletionHandler_, "開始擷取")
        return bool(own_app)

    def stop(self) -> None:
        """Stop capturing; no more callbacks after this returns. Safe to call
        more than once."""
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            _wait_for(stream.stopCaptureWithCompletionHandler_, "停止擷取")
        except RuntimeError as exc:  # the stream may already have died (e.g. display gone)
            if sys.stderr is not None:
                print(f"[screencapture] {exc}", file=sys.stderr)

    def _configuration(self, width: int, height: int, fps: int):
        config = SCStreamConfiguration.alloc().init()
        config.setWidth_(width)
        config.setHeight_(height)
        config.setMinimumFrameInterval_(CMTimeMake(1, fps))
        config.setPixelFormat_(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)
        config.setColorMatrix_(kCGDisplayStreamYCbCrMatrix_ITU_R_709_2)
        config.setShowsCursor_(True)
        config.setQueueDepth_(_QUEUE_DEPTH)
        if self._on_audio is not None:
            config.setCapturesAudio_(True)
            config.setSampleRate_(AUDIO_SAMPLE_RATE)
            config.setChannelCount_(AUDIO_CHANNELS)
            config.setExcludesCurrentProcessAudio_(True)
        return config

    def _add_output(self, output_type) -> None:
        ok, error = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, output_type, None, None
        )
        if not ok:
            raise RuntimeError(f"ScreenCaptureKit 無法加入輸出：{error.localizedDescription()}")

    @staticmethod
    def _pick_display(displays, index: int):
        """Index 0 is the main display (the one with the menu bar), the rest
        follow in ScreenCaptureKit's order."""
        main_id = CGMainDisplayID()
        ordered = sorted(displays, key=lambda display: display.displayID() != main_id)
        if not 0 <= index < len(ordered):
            raise RuntimeError(f"找不到第 {index + 1} 個螢幕")
        return ordered[index]

    def _on_screen_buffer(self, sample_buffer) -> None:
        attachments = CMSampleBufferGetSampleAttachmentsArray(sample_buffer, False)
        if not attachments:
            return
        status = attachments[0].get(SCStreamFrameInfoStatus)
        if status != SCFrameStatusComplete:
            return  # idle/blank/suspended frames carry no new image
        pixels = CMSampleBufferGetImageBuffer(sample_buffer)
        presented_at = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample_buffer))
        CVPixelBufferLockBaseAddress(pixels, kCVPixelBufferLock_ReadOnly)
        try:
            luma_row = CVPixelBufferGetBytesPerRowOfPlane(pixels, 0)
            chroma_row = CVPixelBufferGetBytesPerRowOfPlane(pixels, 1)
            layout = frame_layout(self._frame_width, self._frame_height, luma_row, chroma_row)
            luma = CVPixelBufferGetBaseAddressOfPlane(pixels, 0)
            chroma = CVPixelBufferGetBaseAddressOfPlane(pixels, 1)
            # Copied out: SCK reuses the buffer once this callback returns.
            data = bytes(luma.as_buffer(luma_row * layout.height)) + bytes(
                chroma.as_buffer(chroma_row * layout.height // 2)
            )
        finally:
            CVPixelBufferUnlockBaseAddress(pixels, kCVPixelBufferLock_ReadOnly)
        self._on_video(presented_at, layout, data)

    def _on_audio_buffer(self, sample_buffer) -> None:
        block = CMSampleBufferGetDataBuffer(sample_buffer)
        if block is None:
            return
        length = CMBlockBufferGetDataLength(block)
        status, data = CMBlockBufferCopyDataBytes(block, 0, length, None)
        if status != 0:
            raise RuntimeError(f"CMBlockBufferCopyDataBytes failed: {status}")
        description = CMAudioFormatDescriptionGetStreamBasicDescription(
            CMSampleBufferGetFormatDescription(sample_buffer)
        )
        data = bytes(data)
        if description.mFormatFlags & _kAudioFormatFlagIsNonInterleaved:
            # One buffer per channel, stored one after the other.
            half = len(data) // 2
            data = interleave_f32(data[:half], data[half:])
        presented_at = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample_buffer))
        self._on_audio(presented_at, data)
