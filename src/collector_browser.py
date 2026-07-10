"""
模块三(浏览器辅助版):用 Playwright 起真实无头 Chromium 打开直播间,
在页面脚本执行前 hook 住 window.WebSocket,把浏览器收到的每个二进制帧
转 base64 回传 Python。连接与设备信任由真实浏览器负责(天然过 DEVICE_BLOCKED),
我们只负责接管原始 protobuf 帧,后续交给 M4 解析。

本文件先做连通性测试:统计一段时间内捕获的帧数/字节数,并存前若干帧供 M4 用。
结果写文件,不依赖终端输出。
"""
import sys
import json
import time
import base64
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 在任何页面脚本之前注入:替换 window.WebSocket,捕获二进制帧
HOOK_JS = r"""
(() => {
  const OrigWS = window.WebSocket;
  function PatchedWS(url, protocols) {
    const ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
    try { if (window.__pyOnWsUrl) window.__pyOnWsUrl(String(url)); } catch (e) {}
    ws.addEventListener('message', async (ev) => {
      try {
        let bytes;
        if (ev.data instanceof ArrayBuffer) {
          bytes = new Uint8Array(ev.data);
        } else if (ev.data && typeof ev.data.arrayBuffer === 'function') {
          bytes = new Uint8Array(await ev.data.arrayBuffer());
        } else {
          return; // 文本帧,跳过
        }
        let bin = '';
        const CH = 0x8000;
        for (let i = 0; i < bytes.length; i += CH) {
          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
        }
        if (window.__pyOnWsFrame) window.__pyOnWsFrame(btoa(bin));
      } catch (e) {}
    });
    return ws;
  }
  PatchedWS.prototype = OrigWS.prototype;
  PatchedWS.CONNECTING = OrigWS.CONNECTING;
  PatchedWS.OPEN = OrigWS.OPEN;
  PatchedWS.CLOSING = OrigWS.CLOSING;
  PatchedWS.CLOSED = OrigWS.CLOSED;
  window.WebSocket = PatchedWS;
})();
"""


def collect(web_rid: str, on_frame, seconds: int = 30, headless: bool = True,
            should_stop=None):
    """常驻采集:每收到一个二进制帧,调 on_frame(raw_bytes)。
    运行 seconds 秒后停;should_stop() 返回 True 时提前停(用于切换房间)。"""
    def _on_ws_frame(b64: str):
        try:
            on_frame(base64.b64decode(b64))
        except Exception:
            pass

    with sync_playwright() as p:
        _args = ["--disable-blink-features=AutomationControlled",
                 "--disable-features=IsolateOrigins,site-per-process"]
        # 无头模式:任何会话(含非交互/后台)都能起,也适合打包
        browser = p.chromium.launch(headless=True, args=_args)
        context = browser.new_context(
            user_agent=UA, viewport={"width": 1280, "height": 800}, locale="zh-CN")
        context.expose_function("__pyOnWsFrame", _on_ws_frame)
        context.expose_function("__pyOnWsUrl", lambda u: None)
        context.add_init_script(HOOK_JS)
        page = context.new_page()
        page.goto(f"https://live.douyin.com/{web_rid}",
                  wait_until="domcontentloaded", timeout=30000)
        t0 = time.time()
        while time.time() - t0 < seconds:
            if should_stop and should_stop():
                break
            page.wait_for_timeout(500)
        context.close()
        browser.close()


def run_test(web_rid: str, seconds: int = 20, headless: bool = True,
             save_frames: int = 20) -> dict:
    out = {"stage": "start", "web_rid": web_rid, "headless": headless}
    frames = []
    ws_urls = []

    def on_ws_frame(b64: str):
        frames.append(b64)

    def on_ws_url(url: str):
        ws_urls.append(url)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled",
                      "--disable-features=IsolateOrigins,site-per-process"],
            )
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            context.expose_function("__pyOnWsFrame", on_ws_frame)
            context.expose_function("__pyOnWsUrl", on_ws_url)
            context.add_init_script(HOOK_JS)

            page = context.new_page()
            page.goto(f"https://live.douyin.com/{web_rid}",
                      wait_until="domcontentloaded", timeout=30000)
            out["stage"] = "page_loaded"

            t0 = time.time()
            while time.time() - t0 < seconds:
                page.wait_for_timeout(500)

            out["ws_urls"] = ws_urls[:5]
            out["frame_count"] = len(frames)
            out["total_bytes"] = sum(len(base64.b64decode(f)) for f in frames)
            out["push_ws_seen"] = any("/webcast/im/push/" in u for u in ws_urls)

            # 存前若干帧原始字节,供 M4 解析
            if frames:
                with open("browser_frames.b64", "w", encoding="utf-8") as f:
                    for b in frames[:save_frames]:
                        f.write(b + "\n")

            context.close()
            browser.close()

        out["stage"] = "done"
        out["verdict"] = "FRAMES_CAPTURED" if frames else "NO_FRAMES"
    except Exception as e:
        out["error_type"] = type(e).__name__
        out["error"] = str(e)[:800]
    return out


if __name__ == "__main__":
    web_rid = sys.argv[1] if len(sys.argv) > 1 else "292525714929"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    headless = (sys.argv[3].lower() != "head") if len(sys.argv) > 3 else True
    print(json.dumps(run_test(web_rid, secs, headless), ensure_ascii=False, indent=2))
