
// === final demo map point filter ===
// 默认隐藏额外业务点位，只保留三个书架和安全出口。
// 白色无字按钮可切换显示全部点位。
window.__hideExtraMapPoints = true;

const FINAL_DEMO_VISIBLE_MAP_POINTS = new Set([
  "LIT_SHELF_A3",
  "ENG_SHELF_B1",
  "SCI_SHELF_C1",
  "HAZARD_3_EXIT",
]);

function shouldDrawMapPoint(pointKey, pointObj) {
  if (!window.__hideExtraMapPoints) {
    return true;
  }

  const key = String(pointKey || "");
  if (FINAL_DEMO_VISIBLE_MAP_POINTS.has(key)) {
    return true;
  }

  const name = String((pointObj && pointObj.name) || "");
  return (
    name.includes("文学书架") ||
    name.includes("工科书架") ||
    name.includes("理科书架") ||
    name.includes("安全出口")
  );
}

function initMapPointFilterToggle() {
  if (document.getElementById("map-point-filter-toggle")) {
    return;
  }

  const panels = Array.from(document.querySelectorAll("section, .card, .panel, .map-panel, body > div"));
  const mapPanel = panels.find((el) => (el.textContent || "").includes("地图与导航"));

  if (!mapPanel) {
    return;
  }

  mapPanel.classList.add("map-panel-with-filter-toggle");

  const btn = document.createElement("button");
  btn.id = "map-point-filter-toggle";
  btn.type = "button";
  btn.className = "map-point-filter-toggle is-compact";
  btn.setAttribute("aria-label", "切换地图点位显示");

  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();

    window.__hideExtraMapPoints = !window.__hideExtraMapPoints;
    btn.classList.toggle("is-compact", window.__hideExtraMapPoints);
  });

  mapPanel.appendChild(btn);
}

window.addEventListener("DOMContentLoaded", initMapPointFilterToggle);
setTimeout(initMapPointFilterToggle, 500);

let latestState = null;
let latestMap = null;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function setText(id, value) {
  $(id).textContent = value || "-";
}

function mission(missionId) {
  api("/api/demo/mission", {
    method: "POST",
    body: JSON.stringify({ mission: missionId }),
  }).catch((error) => alert(error.message));
}

function simulateVoice(command) {
  api("/api/demo/simulate-voice", {
    method: "POST",
    body: JSON.stringify({ command }),
  }).catch((error) => alert(error.message));
}

function postEmpty(path) {
  api(path, { method: "POST" }).catch((error) => alert(error.message));
}

function worldToCanvas(map, x, y, width, height, scale, offsetX, offsetY) {
  const origin = map.origin || { x: 0, y: 0 };
  const resolution = map.resolution || 0.02;
  const mx = (x - origin.x) / resolution;
  const my = (y - origin.y) / resolution;
  return [
    offsetX + mx * scale,
    offsetY + (height - my) * scale,
  ];
}

function drawMap() {
  const canvas = $("map-canvas");
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#f7f9fb";
  ctx.fillRect(0, 0, width, height);

  const state = latestState || {};
  const nav = state.navigation || {};
  const map = latestMap && latestMap.ready ? latestMap : null;

  let scale = 90;
  let offsetX = width / 2;
  let offsetY = height / 2;
  let mapWidth = 0;
  let mapHeight = 0;

  if (map && Array.isArray(map.data)) {
    mapWidth = map.width;
    mapHeight = map.height;
    scale = Math.min(width / Math.max(1, mapWidth), height / Math.max(1, mapHeight)) * 0.92;
    offsetX = (width - mapWidth * scale) / 2;
    offsetY = (height - mapHeight * scale) / 2;
    const image = ctx.createImageData(mapWidth, mapHeight);

    // ROS OccupancyGrid 的 data 原点在左下角；
    // Canvas ImageData 的原点在左上角。
    // 因此前端显示时必须把栅格图像按 Y 方向翻转，
    // 否则地图图像会和机器人/目标点/路径坐标不一致。
    for (let gy = 0; gy < mapHeight; gy += 1) {
      for (let gx = 0; gx < mapWidth; gx += 1) {
        const srcIndex = gy * mapWidth + gx;
        const dstY = mapHeight - 1 - gy;
        const dstIndex = dstY * mapWidth + gx;
        const value = map.data[srcIndex];

        let r = 242;
        let g = 246;
        let b = 250;
        let a = 255;

        if (value === 0) {
          // 空闲区域
          r = 252; g = 253; b = 255;
        } else if (value < 0) {
          // 未知区域，淡化显示，不当成障碍
          r = 232; g = 238; b = 245;
        } else if (value >= 65) {
          // 占用区域/墙体
          r = 44; g = 49; b = 55;
        } else {
          // 中间概率区域，浅灰显示
          const shade = 235 - Math.round(value * 1.2);
          r = shade; g = shade; b = shade;
        }

        image.data[dstIndex * 4] = r;
        image.data[dstIndex * 4 + 1] = g;
        image.data[dstIndex * 4 + 2] = b;
        image.data[dstIndex * 4 + 3] = a;
      }
    }

    const temp = document.createElement("canvas");
    temp.width = mapWidth;
    temp.height = mapHeight;
    temp.getContext("2d").putImageData(image, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(temp, offsetX, offsetY, mapWidth * scale, mapHeight * scale);
  } else {
    ctx.strokeStyle = "#d5dee8";
    for (let x = 0; x < width; x += 32) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y < height; y += 32) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#667789";
    ctx.font = "16px sans-serif";
    ctx.fillText("导航地图未连接或未加载", 22, 32);
  }

  const convert = (x, y) => {
    if (map) return worldToCanvas(map, x, y, mapWidth, mapHeight, scale, offsetX, offsetY);
    return [offsetX + x * scale, offsetY - y * scale];
  };

  const path = nav.path || [];
  if (Array.isArray(path) && path.length > 1) {
    ctx.strokeStyle = "#d28b25";
    ctx.lineWidth = 3;
    ctx.beginPath();
    path.forEach((p, index) => {
      const point = Array.isArray(p) ? { x: p[0], y: p[1] } : p;
      const [cx, cy] = convert(point.x, point.y);
      if (index === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
  }

  const points = state.points || {};
  Object.entries(points).forEach(([id, point]) => {
    if (!shouldDrawMapPoint(id, point)) return;
    const [cx, cy] = convert(point.x, point.y);
    ctx.fillStyle = "#2f8f5b";
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#1e2a36";
    ctx.font = "11px sans-serif";
    ctx.fillText(id, cx + 6, cy - 6);
  });

  const goal = nav.goal;
  if (goal && Number.isFinite(goal.x) && Number.isFinite(goal.y)) {
    const [cx, cy] = convert(goal.x, goal.y);
    ctx.fillStyle = "#c43a31";
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    ctx.fill();
  }

  const robot = nav.robot;
  if (robot && Number.isFinite(robot.x) && Number.isFinite(robot.y)) {
    const [cx, cy] = convert(robot.x, robot.y);
    const yaw = robot.yaw || 0;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-yaw);
    ctx.fillStyle = "#1f7a8c";
    ctx.beginPath();
    ctx.moveTo(12, 0);
    ctx.lineTo(-9, -7);
    ctx.lineTo(-6, 0);
    ctx.lineTo(-9, 7);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
}

function renderState(data) {
  latestState = data;
  const order = data.work_order || {};
  const nav = data.navigation || {};
  const orch = data.orchestrator || {};
  $("connection").textContent = nav.available
    ? "导航 dashboard 已连接"
    : `导航未连接：${nav.error || "等待启动"}`;
  $("home-status").textContent = data.home_source || "起点未记录";
  $("orchestrator-state").textContent = orch.state || "idle";
  setText("task", order.current_title || order.current_task);
  setText("stage", order.stage);
  setText("nav-status", order.navigation_status);
  setText("vision-status", order.vision_status);
  setText("voice-status", order.voice_status);
  setText("result", order.result);
  setText("error", order.error);

  const events = $("events");
  events.innerHTML = "";
  (order.events || []).slice(0, 18).forEach((event) => {
    const li = document.createElement("li");
    li.className = event.level || "";
    li.innerHTML = `<span class="time">${event.time}</span> [${event.source}] ${event.text}`;
    events.appendChild(li);
  });
  drawMap();
}

async function refresh() {
  try {
    const data = await api("/api/demo/state");
    renderState(data);
  } catch (error) {
    $("connection").textContent = `演示服务异常：${error.message}`;
  }
}

async function refreshMap() {
  try {
    latestMap = await api("/api/demo/map");
    drawMap();
  } catch (_error) {
    latestMap = null;
  }
}

document.addEventListener("click", (event) => {
  const action = event.target.dataset.action;
  if (action === "cancel") postEmpty("/api/demo/cancel");
  if (action === "emergency-stop") postEmpty("/api/demo/emergency-stop");
  if (action === "emergency-release") postEmpty("/api/demo/emergency-release");
});

window.addEventListener("resize", drawMap);
refresh();
refreshMap();
setInterval(refresh, 800);
setInterval(refreshMap, 3000);

// Camera still-frame refresh.
// 后端已缓存最新帧，这里只刷新浏览器图片。
setInterval(() => {
  const img = document.getElementById("camera-feed");
  if (img) {
    img.src = `/camera_annotated.jpg?t=${Date.now()}`;
  }
}, 500);


// === final demo environment status mock refresh ===
// DHT11 已接入 P89，当前演示阶段用稳定环境值展示。
function updateEnvironmentStatusPanel() {
  const tempEl = document.getElementById("env-temperature");
  const humEl = document.getElementById("env-humidity");
  const stateEl = document.getElementById("env-state");

  if (!tempEl || !humEl || !stateEl) {
    return;
  }

  const now = Date.now() / 1000;
  const temp = 26.4 + Math.sin(now / 18) * 0.2;
  const hum = 48 + Math.round(Math.sin(now / 22) * 1);

  tempEl.textContent = `${temp.toFixed(1)}℃`;
  humEl.textContent = `${hum}%`;
  stateEl.textContent = "正常";
}

setInterval(updateEnvironmentStatusPanel, 2000);
window.addEventListener("DOMContentLoaded", updateEnvironmentStatusPanel);


// === final demo AI vision model panel refresh ===
function updateAIVisionPanelFromState(state) {
  const badge = document.getElementById("ai-vision-status");
  const book = document.getElementById("ai-book-status");
  const lost = document.getElementById("ai-lost-status");
  const hazard = document.getElementById("ai-hazard-status");
  const result = document.getElementById("ai-vision-result");

  if (!badge || !book || !lost || !hazard || !result) {
    return;
  }

  const wo = state && state.work_order ? state.work_order : {};
  const title = String(wo.current_title || wo.title || "");
  const stage = String(wo.stage || "");
  const visionStatus = String(wo.vision_status || "");
  const detectResult = String(wo.result || "");

  badge.classList.remove("is-running", "is-alert");

  book.textContent = "本地 ArUco 已接入";
  lost.textContent = "Qwen-VL 待调用";
  hazard.textContent = "Qwen-VL 待调用";

  if (title.includes("寻书") || title.includes("书架") || stage.includes("SHELF") || stage.includes("BOOK")) {
    badge.textContent = "分析中";
    badge.classList.add("is-running");
    book.textContent = "ArUco 图书定位 / 书脊标记识别";
    result.textContent = detectResult
      ? `最近输出：${detectResult}`
      : "最近输出：正在分析书架图像，定位目标图书与错放图书";
    return;
  }

  if (title.includes("遗失") || stage.includes("LOST")) {
    badge.textContent = "分析中";
    badge.classList.add("is-running");
    lost.textContent = "Qwen-VL 遗失物检测";
    result.textContent = detectResult
      ? `最近输出：${detectResult}`
      : "最近输出：正在检测地面钥匙、校园卡、背包等遗失物";
    return;
  }

  if (title.includes("高危") || stage.includes("HAZARD")) {
    badge.textContent = "告警";
    badge.classList.add("is-alert");
    hazard.textContent = "Qwen-VL 高危场景识别";
    result.textContent = detectResult
      ? `最近输出：${detectResult}`
      : "最近输出：正在识别插座乱接、线缆绊倒、出口阻塞等风险";
    return;
  }

  if (visionStatus && visionStatus !== "-") {
    badge.textContent = "就绪";
    result.textContent = `最近输出：${visionStatus}`;
  } else {
    badge.textContent = "就绪";
    result.textContent = "最近输出：等待巡检任务触发视觉分析";
  }
}

function refreshAIVisionPanel() {
  fetch("/api/demo/state")
    .then((resp) => resp.json())
    .then((state) => updateAIVisionPanelFromState(state))
    .catch(() => {});
}

setInterval(refreshAIVisionPanel, 1000);
window.addEventListener("DOMContentLoaded", refreshAIVisionPanel);
