import socket
import struct
import threading
import time


PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<rect width="960" height="540" fill="#18202a"/>
<rect x="36" y="36" width="888" height="468" rx="8" fill="#202b38" stroke="#435163" stroke-width="2"/>
<text x="480" y="250" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" fill="#e6edf5">摄像头连接中</text>
<text x="480" y="300" text-anchor="middle" font-family="Arial, sans-serif" font-size="20" fill="#9fb0c3">等待板端 5000 JPEG 流</text>
</svg>"""


class CameraProxy:
    """
    后台单连接读取板端 board_stream_server，缓存最新 JPEG。

    板端协议：
        每帧 = 4字节网络序 uint32 长度 + JPEG数据

    Web 侧：
        /camera.jpg 直接返回最近缓存帧，不再每次请求都连接板端。
    """

    def __init__(self, config):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.host = str(
            self.config.get("board_host")
            or self.config.get("host")
            or "192.168.43.192"
        )
        self.port = int(
            self.config.get("board_port")
            or self.config.get("port")
            or 5000
        )
        self.timeout_sec = float(self.config.get("timeout_sec", 5.0))
        self.max_frame_bytes = int(self.config.get("max_frame_bytes", 5 * 1024 * 1024))

        self._lock = threading.RLock()
        self._latest_jpeg = None
        self._latest_time = 0.0
        self._last_error = ""
        self._running = False
        self._thread = None

    def placeholder_image(self):
        return PLACEHOLDER_SVG.encode("utf-8")

    def start(self):
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @staticmethod
    def _read_exact(sock, size):
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("camera stream closed")
            data += chunk
        return data

    def _reader_loop(self):
        while self._running:
            try:
                with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                    sock.settimeout(self.timeout_sec)
                    with self._lock:
                        self._last_error = ""

                    while self._running:
                        raw_len = self._read_exact(sock, 4)
                        size = struct.unpack("!I", raw_len)[0]
                        if size <= 0 or size > self.max_frame_bytes:
                            raise ValueError(f"invalid jpeg frame size: {size}")

                        frame = self._read_exact(sock, size)

                        if not frame.startswith(b"\xff\xd8"):
                            raise ValueError("bad JPEG start marker")
                        if not frame.endswith(b"\xff\xd9"):
                            # 有时网络刚重连会遇到半帧，直接丢弃并重连
                            raise ValueError("received data is not a complete JPEG frame")

                        with self._lock:
                            self._latest_jpeg = frame
                            self._latest_time = time.time()
                            self._last_error = ""

            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                time.sleep(0.5)

    def latest_jpeg(self, max_age_sec=3.0):
        with self._lock:
            if self._latest_jpeg and (time.time() - self._latest_time) <= max_age_sec:
                return self._latest_jpeg
            return None

    def status(self):
        with self._lock:
            return {
                "enabled": self.enabled,
                "host": self.host,
                "port": self.port,
                "has_frame": self._latest_jpeg is not None,
                "frame_age_sec": None if not self._latest_jpeg else round(time.time() - self._latest_time, 3),
                "last_error": self._last_error,
            }


class BoardJpegStreamClient:
    def __init__(self, host, port):
        self.host = host
        self.port = int(port)
