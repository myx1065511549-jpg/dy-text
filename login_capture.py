# 一次性登录:起有头chromium,等你扫码,把登录态存到 auth_state.local.json
# 用法: python login_capture.py  然后在弹出窗口右上角点登录扫码
import os, time, json
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# 存到 src/(与 danmu.db 同目录,server 的商品采集从这里读登录态)
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "auth_state.local.json")
RID = "292525714929"

def main():
    with sync_playwright() as p:
        args = ["--disable-blink-features=AutomationControlled"]
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                if channel:
                    browser = p.chromium.launch(headless=False, channel=channel, args=args)
                else:
                    browser = p.chromium.launch(headless=False, args=args)
                print(f">> 使用浏览器: {channel or 'playwright-chromium'}")
                break
            except Exception as e:
                print(f"   {channel or 'playwright-chromium'} 不可用: {str(e)[:80]}")
                browser = None
        if browser is None:
            print(">> 没有可用的有头浏览器,请装Chrome或Edge,或运行 playwright install chromium")
            return
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1280, "height": 900},
                                  locale="zh-CN")
        page = ctx.new_page()
        page.goto(f"https://live.douyin.com/{RID}",
                  wait_until="domcontentloaded", timeout=40000)
        print(">> 窗口已打开,请点右上角[登录]并用抖音APP扫码,等待中...")
        ok = False
        for i in range(180):
            try:
                cks = ctx.cookies()
            except Exception:
                cks = []
            if any(c["name"] in ("sessionid", "sessionid_ss") and c.get("value")
                   for c in cks):
                ok = True
                break
            if i % 10 == 0 and i:
                print(f"   ...仍在等待扫码 ({i}s)")
            time.sleep(1)
        if ok:
            ctx.storage_state(path=STATE)
            print(">> 登录成功,登录态已存到", STATE)
        else:
            print(">> 超时未检测到登录,请重试")
        browser.close()
    print(json.dumps({"login_ok": ok, "state_saved": ok}, ensure_ascii=False))

if __name__ == "__main__":
    main()
