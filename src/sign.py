"""
模块二:签名生成(诊断版)。
用 mini-racer 在纯 V8 里执行抖音官方 webmssdk.es5.js。
SDK 依赖浏览器环境,这里补一层最小 shim(window/navigator/document/location 等),
加载后先探测 byted_acrawler 上有哪些方法、frontierSign 是否可用。

先跑通"能加载 + 能看到签名入口",再谈实际签名调用。
"""
import os
import json
from py_mini_racer import MiniRacer

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(HERE, "vendor", "webmssdk.es5.js")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 最小浏览器环境 shim:纯 V8 没有 DOM,SDK 会读 window/navigator/document 等。
# 先给最常被读的字段,缺什么后续按报错补什么。
ENV_JS = r"""
var global = globalThis;
var window = globalThis;
var self = globalThis;
window.navigator = {
  userAgent: "__UA__",
  platform: "Win32",
  language: "zh-CN",
  languages: ["zh-CN", "zh"],
  appName: "Netscape",
  appVersion: "5.0 (Windows NT 10.0; Win64; x64)",
  cookieEnabled: true,
  webdriver: false
};
window.location = {
  href: "https://live.douyin.com/",
  protocol: "https:",
  host: "live.douyin.com",
  hostname: "live.douyin.com",
  origin: "https://live.douyin.com",
  pathname: "/",
  search: ""
};
window.screen = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, colorDepth: 24 };
window.history = { length: 1 };
window.localStorage = (function(){ var s={}; return {
  getItem:function(k){return k in s?s[k]:null;}, setItem:function(k,v){s[k]=""+v;},
  removeItem:function(k){delete s[k];}, clear:function(){s={};} }; })();
window.sessionStorage = window.localStorage;
function _el(){ return {
  style:{}, setAttribute:function(){}, getAttribute:function(){return null;},
  appendChild:function(){}, addEventListener:function(){}, removeEventListener:function(){},
  getContext:function(){ return { measureText:function(){return {width:0};}, fillText:function(){},
     getImageData:function(){return {data:[]};}, fillRect:function(){}, save:function(){}, restore:function(){} }; },
  toDataURL:function(){ return "data:image/png;base64,"; },
  getElementsByTagName:function(){return [];}, children:[], childNodes:[]
}; }
window.document = {
  cookie: "",
  referrer: "https://live.douyin.com/",
  title: "douyin",
  readyState: "complete",
  documentElement: _el(),
  body: _el(),
  createElement: function(){ return _el(); },
  getElementById: function(){ return null; },
  getElementsByTagName: function(){ return [ _el() ]; },
  getElementsByClassName: function(){ return []; },
  querySelector: function(){ return null; },
  querySelectorAll: function(){ return []; },
  addEventListener: function(){}, removeEventListener: function(){},
  createEvent: function(){ return { initEvent:function(){} }; }
};
window.addEventListener = function(){};
window.removeEventListener = function(){};
window.setTimeout = function(f){ try{ if(typeof f==='function') f(); }catch(e){} return 0; };
window.setInterval = function(){ return 0; };
window.clearTimeout = function(){};
window.clearInterval = function(){};
window.btoa = function(s){ return s; };
window.performance = { now: function(){ return 0; } };
""".replace("__UA__", UA)

PROBE_JS = r"""
(function(){
  var ba = window.byted_acrawler;
  return JSON.stringify({
    typeof_ba: typeof ba,
    ba_keys: ba ? Object.keys(ba) : null,
    typeof_frontierSign: ba ? typeof ba.frontierSign : null,
    typeof_sign: ba ? typeof ba.sign : null,
    typeof_init: ba ? typeof ba.init : null
  });
})();
"""


def load_sdk():
    ctx = MiniRacer()
    ctx.eval(ENV_JS)
    with open(SDK_PATH, "r", encoding="utf-8") as f:
        sdk = f.read()
    ctx.eval(sdk)
    return ctx


class Signer:
    """加载一次 SDK,保持 V8 上下文常驻,反复算签名。"""

    def __init__(self):
        self.ctx = load_sdk()

    def sign(self, params: dict) -> str:
        """把 wss 查询参数对象交给 frontierSign,返回 signature(X-Bogus)。"""
        self.ctx.eval("var __sp = " + json.dumps(params, ensure_ascii=False) + ";")
        r = self.ctx.eval(
            "JSON.stringify(window.byted_acrawler.frontierSign(__sp))"
        )
        return json.loads(r)["X-Bogus"]


def diagnose():
    result = {"stage": "start"}
    try:
        ctx = MiniRacer()
        ctx.eval(ENV_JS)
        result["stage"] = "env_ok"
        with open(SDK_PATH, "r", encoding="utf-8") as f:
            sdk = f.read()
        result["sdk_len"] = len(sdk)
        ctx.eval(sdk)
        result["stage"] = "sdk_loaded"
        probe = ctx.eval(PROBE_JS)
        result["probe"] = json.loads(probe)
        result["stage"] = "probed"
    except Exception as e:
        result["error_type"] = type(e).__name__
        result["error"] = str(e)[:800]
    return result


if __name__ == "__main__":
    print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
