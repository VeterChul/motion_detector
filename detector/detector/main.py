"""Точка входа: чтение RTSP + heartbeat в MQTT."""

import logging
import os
import signal
import sys
import threading
import time

import yaml

from .publisher import Publisher
from .source import RTSPSource


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    log = logging.getLogger("detector")

    with open("/app/config.yaml") as f:
        cfg = yaml.safe_load(f)

    # ─── RTSP ────────────────────────────────
    mtx_user = os.environ["MTX_APP_USER"]
    mtx_pass = os.environ["MTX_APP_PASS"]
    mtx = cfg["mediamtx"]
    url = f"rtsp://{mtx_user}:{mtx_pass}@{mtx['host']}:{mtx['port']}/{mtx['path']}"

    # ─── MQTT ────────────────────────────────
    publisher = Publisher(
        host=cfg["mqtt"]["host"],
        port=cfg["mqtt"]["port"],
        user=os.environ["MQTT_USER"],
        password=os.environ["MQTT_PASS"],
        prefix=cfg["mqtt"]["topic_prefix"],
    )
    publisher.connect()
    log.info("MQTT publisher started")

    # ─── Состояние ───────────────────────────
    state = {
        "started_at": time.time(),
        "frame_count": 0,
        "last_frame_ts": None,
    }
    stop_event = threading.Event()

    # ─── Поток heartbeat ─────────────────────
    def heartbeat_loop():
        interval = cfg["heartbeat"]["interval"]
        while not stop_event.wait(interval):
            now = time.time()
            last = state["last_frame_ts"]
            publisher.publish(
                "heartbeat",
                {
                    "t": round(now, 3),
                    "uptime": round(now - state["started_at"], 1),
                    "frames": state["frame_count"],
                    "last_frame_age": round(now - last, 3) if last else None,
                },
            )

    hb = threading.Thread(target=heartbeat_loop, daemon=True, name="heartbeat")
    hb.start()

    # ─── Обработка сигналов ──────────────────
    def on_signal(signum, frame):
        log.info("Signal %s received, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    # ─── Основной цикл ───────────────────────
    source = RTSPSource(url, transport=mtx["transport"])
    log.info("Detector started")

    count = 0
    last_log = 0.0
    frame_log_interval = cfg.get("log", {}).get("frame_log_interval", 5) * 5

    try:
        for frame, ts in source.frames():
            if stop_event.is_set():
                break

            count += 1
            state["frame_count"] = count
            state["last_frame_ts"] = ts

            if count - last_log >= frame_log_interval:
                log.info("Received %d frames, last: shape=%s", count, frame.shape)
                last_log = count
    finally:
        stop_event.set()
        publisher.stop()
        log.info("Detector stopped")


if __name__ == "__main__":
    main()
