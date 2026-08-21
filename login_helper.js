const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const BASE = __dirname;
const PORT = 8849;
const NODE = path.join(BASE, '_internal', 'playwright', 'driver', 'node.exe');
const CAPTURE = path.join(BASE, 'login_capture.js');
const AUTH_STATE = path.join(BASE, 'auth_state.local.json');
const RESTART_WORKER = path.join(BASE, 'restart-browser-worker.exe');
const STOP_DASHBOARD = path.join(BASE, 'stop-dashboard.exe');
const ALLOWED_ORIGINS = new Set([
  'http://127.0.0.1:8848',
  'http://localhost:8848',
]);

let loginProcess = null;
let loginState = {
  phase: 'idle',
  message: '等待登录',
};

function sendJson(req, res, statusCode, body) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.has(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Douyin-Dashboard');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.writeHead(statusCode);
  res.end(JSON.stringify(body));
}

function stopProcessTree(pid) {
  if (!pid) return;
  spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
    windowsHide: true,
    stdio: 'ignore',
  });
}

function startLogin() {
  if (loginProcess) return;
  const startedAt = Date.now();
  loginState = {
    phase: 'running',
    message: '请在新打开的抖音窗口中完成登录',
  };

  try {
    loginProcess = spawn(NODE, [CAPTURE], {
      cwd: BASE,
      windowsHide: true,
      stdio: 'ignore',
    });
  } catch (error) {
    loginProcess = null;
    loginState = { phase: 'failed', message: '登录窗口启动失败' };
    return;
  }

  loginProcess.once('error', () => {
    loginProcess = null;
    loginState = { phase: 'failed', message: '登录窗口启动失败' };
  });

  loginProcess.once('exit', code => {
    loginProcess = null;
    let saved = false;
    try {
      saved = fs.existsSync(AUTH_STATE) && fs.statSync(AUTH_STATE).mtimeMs >= startedAt - 1000;
    } catch {}

    if (code !== 0 || !saved) {
      loginState = { phase: 'failed', message: '未检测到登录成功，请重新登录' };
      return;
    }

    loginState = { phase: 'restarting', message: '登录成功，正在重新连接商品采集' };
    const result = spawnSync(RESTART_WORKER, [], {
      cwd: BASE,
      windowsHide: true,
      stdio: 'ignore',
      timeout: 15000,
    });

    loginState = {
      phase: 'success',
      message: result.status === 0
        ? '登录成功，商品采集正在恢复'
        : '登录成功，重新启动看板后商品采集即可生效',
    };
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const originAllowed = ALLOWED_ORIGINS.has(req.headers.origin);

  if (req.method === 'OPTIONS') {
    sendJson(req, res, originAllowed ? 204 : 403, {});
    return;
  }

  if (req.method === 'GET' && url.pathname === '/status') {
    sendJson(req, res, 200, loginState);
    return;
  }

  if (req.method === 'POST' && url.pathname === '/login') {
    if (!originAllowed && req.headers['x-douyin-dashboard'] !== 'login') {
      sendJson(req, res, 403, { phase: 'failed', message: '请求来源不受信任' });
      return;
    }
    startLogin();
    sendJson(req, res, 202, loginState);
    return;
  }

  if (req.method === 'POST' && url.pathname === '/shutdown') {
    if (!originAllowed && req.headers['x-douyin-dashboard'] !== 'stop') {
      sendJson(req, res, 403, { ok: false });
      return;
    }
    if (loginProcess) stopProcessTree(loginProcess.pid);
    const result = spawnSync(STOP_DASHBOARD, [], {
      cwd: BASE,
      windowsHide: true,
      stdio: 'ignore',
      timeout: 15000,
    });
    sendJson(req, res, result.status === 0 ? 200 : 500, { ok: result.status === 0 });
    server.close();
    setTimeout(() => process.exit(0), 250);
    return;
  }

  sendJson(req, res, 404, { error: 'not_found' });
});

server.on('error', error => {
  process.exit(error.code === 'EADDRINUSE' ? 0 : 1);
});

server.listen(PORT, '127.0.0.1');
