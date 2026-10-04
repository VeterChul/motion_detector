"""Чтение RTSP-потока через PyAV."""

import logging
import time

import av

log = logging.getLogger(__name__)


class RTSPSource:
    def __init__(self, url: str, transport: str = "tcp"):
        self.url = url
        self.transport = transport

    def frames(self):
        """Бесконечный цикл: подключиться и отдавать кадры.

        При разрыве — переподключиться через 3 секунды.
        """
        while True:
            try:
                log.info("Connecting to %s", self.url)
                container = av.open(self.url, options={"rtsp_transport": self.transport})
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                log.info("Connected, decoding...")

                for frame in container.decode(stream):
                    yield frame.to_ndarray(format="bgr24"), time.time()

            except Exception as e:
                log.warning("RTSP error: %s. Reconnecting in 3s...", e)
                time.sleep(3)
