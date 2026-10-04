"""Публикация событий в MQTT."""

import json
import logging
import time

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


class Publisher:
    def __init__(self, host, port, user, password, prefix):
        self.host = host
        self.port = port
        self.prefix = prefix
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"detector-{int(time.time())}",
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(user, password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            log.info("MQTT connected")
        else:
            log.error("MQTT connect failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("MQTT disconnected: %s", reason_code)

    def connect(self):
        # connect_async + loop_start: сеть работает в фоне, не блокирует основной поток
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def publish(self, topic: str, payload: dict, qos: int = 1, retain: bool = False):
        full = f"{self.prefix}/{topic}"
        info = self.client.publish(full, json.dumps(payload), qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("Publish to %s failed: rc=%s", full, info.rc)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
