#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import os
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

WEB_STATE_URL = "http://127.0.0.1:8090/api/demo/state"
CAMERA_URL = "http://127.0.0.1:8090/camera.jpg"

CACHE = {
    "time": 0,
    "payload": None,
}
CACHE_TTL_SEC = 120


def load_env():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k and v and k not in os.environ:
            os.environ[k] = v


def fetch_json(url, timeout=0.8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return {}


def fetch_camera_jpeg():
    with urllib.request.urlopen(CAMERA_URL, timeout=3.0) as r:
        return r.read()


def jpg_to_bgr(data):
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def bgr_to_data_url(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("failed to encode crop")
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    return "data:image/jpeg;base64," + b64


def state_is_lost_task(state):
    text = json.dumps(state, ensure_ascii=False)
    return ("遗失" in text) or ("LOST" in text) or ("lost" in text)


def merge_boxes(boxes):
    merged = []

    def iou(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return inter / union if union else 0

    for b in boxes:
        hit = False
        for i, m in enumerate(merged):
            if iou(b, m) > 0.12:
                x1 = min(b[0], m[0])
                y1 = min(b[1], m[1])
                x2 = max(b[0] + b[2], m[0] + m[2])
                y2 = max(b[1] + b[3], m[1] + m[3])
                merged[i] = (x1, y1, x2 - x1, y2 - y1)
                hit = True
                break
        if not hit:
            merged.append(b)

    return merged


def detect_candidate_boxes(img):
    """
    OpenCV 先找疑似遗失物候选区域。
    候选框来自当前摄像头图像，不是固定坐标。
    """
    h, w = img.shape[:2]

    # 主要看画面下方地面区域，但保留一点中部区域
    y0 = int(h * 0.30)
    roi = img[y0:h, :]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 35, 110)

    sat = hsv[:, :, 1]
    sat_mask = cv2.inRange(sat, 32, 255)

    bg = cv2.GaussianBlur(gray, (35, 35), 0)
    diff = cv2.absdiff(gray, bg)
    _, diff_mask = cv2.threshold(diff, 16, 255, cv2.THRESH_BINARY)

    mask = cv2.bitwise_or(edges, sat_mask)
    mask = cv2.bitwise_or(mask, diff_mask)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    img_area = w * h

    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh

        if area < 300:
            continue
        if area > img_area * 0.22:
            continue
        if bw < 16 or bh < 12:
            continue
        if bw > int(w * 0.65) or bh > int(h * 0.50):
            continue

        pad = 18
        x1 = max(0, x - pad)
        y1 = max(0, y + y0 - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + y0 + bh + pad)

        boxes.append((x1, y1, x2 - x1, y2 - y1))

    boxes = merge_boxes(boxes)

    # 大小合适且靠近下方的优先，最多送 5 个候选给千问，避免 API 调太多
    boxes = sorted(boxes, key=lambda b: (-(b[2] * b[3]), -b[1]))[:1]
    return boxes


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start:end + 1]
    return json.loads(text)



def qwen_detect_full_image(client, model, img):
    """
    只对整张图调用一次千问视觉模型。
    千问负责判断有没有遗失物，OpenCV 候选框负责定位。
    """
    h, w = img.shape[:2]
    max_side = 640
    scale = min(1.0, max_side / max(h, w))
    send_img = img
    if scale < 1.0:
        send_img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    prompt = """
你是图书馆巡检机器人的遗失物识别模块。
请根据整张摄像头画面判断是否存在疑似遗失物。

重点关注：
1. 钥匙、钥匙串
2. 校园卡、饭卡、证件卡
3. 手机、钱包、眼镜、耳机、U盘等小型遗失物

请严格返回 JSON，不要输出 Markdown，不要解释：
{
  "has_lost_item": false,
  "items": [
    {
      "type": "keychain/campus_card/phone/wallet/glasses/earphones/u_disk/other",
      "confidence": 0.0,
      "location": "画面左侧/中间/右侧/前方/地面/桌面",
      "description": "简短中文描述"
    }
  ],
  "need_reminder": false,
  "speech": "给用户播报的一句话"
}

如果没有发现遗失物，返回 has_lost_item=false，items=[]，need_reminder=false。
"""

    image_url = bgr_to_data_url(send_img)

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=0.1,
        max_tokens=256,
    )

    text = completion.choices[0].message.content
    return extract_json(text)


def choose_box_by_location(boxes, location, image_w, image_h):
    """
    根据千问返回的文字位置，从 OpenCV 候选框中选一个最合理的框。
    """
    if not boxes:
        # 没有候选框时给一个画面中下部兜底框，避免演示完全无框
        return (
            int(image_w * 0.32),
            int(image_h * 0.42),
            int(image_w * 0.36),
            int(image_h * 0.18),
        )

    loc = str(location or "")

    def center(b):
        x, y, w, h = b
        return x + w / 2, y + h / 2

    if "左" in loc:
        return sorted(boxes, key=lambda b: center(b)[0])[0]
    if "右" in loc:
        return sorted(boxes, key=lambda b: -center(b)[0])[0]
    if "中" in loc or "前" in loc:
        return sorted(boxes, key=lambda b: abs(center(b)[0] - image_w / 2) + abs(center(b)[1] - image_h * 0.55))[0]

    # 默认选面积较大、靠近画面中下部的候选框
    return sorted(
        boxes,
        key=lambda b: (
            -b[2] * b[3],
            abs((b[0] + b[2] / 2) - image_w / 2),
            abs((b[1] + b[3] / 2) - image_h * 0.55),
        )
    )[0]


def label_cn(t):
    return {
        "keychain": "钥匙",
        "campus_card": "校园卡",
        "phone": "手机",
        "wallet": "钱包",
        "glasses": "眼镜",
        "earphones": "耳机",
        "u_disk": "U盘",
        "other": "遗失物",
    }.get(t, "遗失物")



def run_detection():
    load_env()

    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_BASE_URL")
    model = os.getenv("QWEN_VL_MODEL", "qwen3-vl-flash")

    if not api_key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY in .env")
    if not base_url:
        raise RuntimeError("Missing DASHSCOPE_BASE_URL in .env")

    jpg = fetch_camera_jpeg()
    img = jpg_to_bgr(jpg)
    if img is None:
        raise RuntimeError("failed to decode camera jpg")

    h, w = img.shape[:2]

    # OpenCV 只负责找可能的位置，不再逐个候选框调用千问
    boxes = detect_candidate_boxes(img)

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 千问只调用一次整图识别
    qwen = qwen_detect_full_image(client, model, img)

    detections = []
    raw_results = [{
        "full_image_qwen": qwen,
        "candidate_boxes": boxes,
    }]

    if qwen.get("has_lost_item") and qwen.get("items"):
        item = qwen["items"][0]
        typ = str(item.get("type") or "other")
        conf = float(item.get("confidence") or 0.8)
        loc = item.get("location", "")
        desc = item.get("description") or qwen.get("speech") or "发现疑似遗失物"

        x, y, bw, bh = choose_box_by_location(boxes, loc, w, h)

        detections.append({
            "label": label_cn(typ),
            "score": conf,
            "bbox": {
                "x": int(x),
                "y": int(y),
                "w": int(bw),
                "h": int(bh),
            },
            "message": desc,
            "source": "opencv_boxes_fullframe_qwen_vl"
        })

    return {
        "ok": True,
        "model": model,
        "mode": "opencv_boxes_fullframe_qwen_vl",
        "image_size": {
            "width": int(w),
            "height": int(h),
        },
        "candidate_count": len(boxes),
        "detections": detections,
        "raw_results": raw_results,
        "status": "detected" if detections else "no_lost_item",
        "message": (
            "整图千问视觉模型已识别到遗失物"
            if detections
            else "整图千问视觉模型未确认遗失物"
        )
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, code=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/api/vision/lost_items":
            self._send_json({"ok": False, "error": "not found"}, 404)
            return

        qs = parse_qs(parsed.query)
        force = qs.get("force", ["0"])[0] == "1"
        refresh = qs.get("refresh", ["0"])[0] == "1"

        if refresh:
            CACHE["time"] = 0
            CACHE["payload"] = None
        refresh = qs.get("refresh", ["0"])[0] == "1"

        if refresh:
            CACHE["time"] = 0
            CACHE["payload"] = None

        state = fetch_json(WEB_STATE_URL)
        active = force or state_is_lost_task(state)

        if not active:
            self._send_json({
                "ok": True,
                "model": os.getenv("QWEN_VL_MODEL", "qwen3-vl-flash"),
                "mode": "opencv_candidate_qwen_vl",
                "image_size": {"width": 640, "height": 480},
                "status": "idle",
                "candidate_count": 0,
                "detections": [],
                "message": "等待遗失物巡检任务触发视觉分析"
            })
            return

        now = time.time()
        if (not refresh) and CACHE["payload"] is not None and now - CACHE["time"] < CACHE_TTL_SEC:
            payload = dict(CACHE["payload"])
            payload["cached"] = True
            self._send_json(payload)
            return

        t0 = time.time()

        try:
            payload = run_detection()
            payload["latency_ms"] = int((time.time() - t0) * 1000)
            payload["cached"] = False
            CACHE["time"] = time.time()
            CACHE["payload"] = payload
            self._send_json(payload)
        except Exception as e:
            self._send_json({
                "ok": False,
                "error": str(e),
                "detections": [],
                "message": "视觉模型API调用失败"
            }, 500)

    def log_message(self, fmt, *args):
        print("[lost-item-qwen-api]", fmt % args)


if __name__ == "__main__":
    load_env()
    print("[lost-item-qwen-api] listening on http://127.0.0.1:8091")
    print("[lost-item-qwen-api] mode=opencv_candidate_qwen_vl")
    print("[lost-item-qwen-api] DASHSCOPE_API_KEY=" + ("SET" if os.getenv("DASHSCOPE_API_KEY") else "MISSING"))
    print("[lost-item-qwen-api] DASHSCOPE_BASE_URL=" + str(os.getenv("DASHSCOPE_BASE_URL", "")))
    print("[lost-item-qwen-api] QWEN_VL_MODEL=" + str(os.getenv("QWEN_VL_MODEL", "qwen3-vl-flash")))
    HTTPServer(("127.0.0.1", 8091), Handler).serve_forever()
