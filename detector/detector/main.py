"""Точка входа: чтение RTSP + детекция движения + heartbeat в MQTT."""

import logging
import os
import signal
import sys
import threading
import time
import cv2
import yaml

from datetime import datetime, timezone

from .motion import MotionDetector
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

    # ─── Детектор движения ───────────────────
    det_cfg = cfg["detector"]
    detector = MotionDetector(
        min_area_ratio=det_cfg["min_area_ratio"],
        width=det_cfg["width"],
        warmup_frames=det_cfg["warmup_frames"],
    )
    process_every = det_cfg["process_every"]
    post_roll = det_cfg["post_roll"]
    max_skreen_count = det_cfg["max_skreen_count"]

    # ─── Состояние ───────────────────────────
    state = {
        "started_at": time.time(),
        "frame_count": 0,
        "last_frame_ts": None,
    }
    motion_state = {
        "active": False,
        "last_seen": None,
    }
    stop_event = threading.Event()
    # Состояние кадров — инициализируем до цикла
    snap_state = {
        "dir": None,
        "count": 0,
    }

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
                    "motion_active": motion_state["active"],
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

    snaps_dir = "/recordings/skreen"
    os.makedirs(snaps_dir, exist_ok=True)

    try:
        for frame, ts in source.frames():
            if stop_event.is_set():
                break

            count += 1
            state["frame_count"] = count
            state["last_frame_ts"] = ts

            # ─── Логирование кадров ────────────
            if count - last_log >= frame_log_interval:
                log.info("Received %d frames, last: shape=%s", count, frame.shape)
                last_log = count

            # ─── Детекция движения ─────────────
            if count % process_every != 0:
                continue

            has_motion = detector.process(frame)

            if has_motion:
                motion_state["last_seen"] = ts
                if not motion_state["active"]:
                    motion_state["active"] = True
                    skreen_count = 0

                    dirname = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
                    snap_state["dir"] = os.path.join(snaps_dir, dirname)
                    os.makedirs(snap_state["dir"], exist_ok=True)
                    snap_state["count"] = 0

                    publisher.publish("motion_started", {"t": round(ts, 3)})
                    log.info("motion_started at %.3f", ts)

                if snap_state["dir"] and snap_state["count"] < max_skreen_count:
                    snap_state["count"] += 1
                    filepath = os.path.join(
                        snap_state["dir"],
                        f"{snap_state['count']:03d}.jpg",
                    )
                    ok = cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ok:
                        log.info("saved frame: %s", filepath)
                    else:
                        log.error("failed to save frame: %s", filepath)

            else:
                if motion_state["active"] and motion_state["last_seen"]:

                    silence = ts - motion_state["last_seen"]
                    if silence >= post_roll:
                        motion_state["active"] = False
                        snap_state["dir"] = None

                        publisher.publish(
                            "motion_stopped",
                            {
                                "t": round(ts, 3),
                                "last_motion": round(motion_state["last_seen"], 3),
                            },
                        )
                        log.info(
                            "motion_stopped, last motion at %.3f",
                            motion_state["last_seen"],
                        )
    finally:
        stop_event.set()
        publisher.stop()
        log.info("Detector stopped")


if __name__ == "__main__":
    main()
