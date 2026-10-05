"""Детекция движения через MOG2."""

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)


class MotionDetector:
    def __init__(self, min_area_ratio=0.005, width=320, warmup_frames=100):
        self.min_area_ratio = min_area_ratio
        self.width = width
        self.warmup_frames = warmup_frames
        self.frame_count = 0

        # MOG2 без теней, с разумной историей
        self.back_sub = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=16,
            detectShadows=False,
        )

    def _preprocess(self, frame):
        """Уменьшить и перевести в grayscale."""
        h, w = frame.shape[:2]
        scale = self.width / w
        small = cv2.resize(frame, (self.width, int(h * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (21, 21), 0)

    def process(self, frame):
        """Вернуть True, если в кадре есть движение.

        Первые warmup_frames кадров только учит фон и всегда возвращает False.
        """
        self.frame_count += 1
        small = self._preprocess(frame)
        mask = self.back_sub.apply(small)

        if self.frame_count <= self.warmup_frames:
            return False

        # Морфология: убираем мелкий шум
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # Площадь движения
        motion_pixels = int(np.count_nonzero(mask))
        total_pixels = mask.shape[0] * mask.shape[1]
        ratio = motion_pixels / total_pixels

        return ratio >= self.min_area_ratio
