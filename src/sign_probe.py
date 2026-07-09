"""
探测 frontierSign 的实际入参/出参结构。
复用 sign.load_sdk 起好带 shim 的 V8 环境,用仿真 wss 参数调用 frontierSign,
把返回原样 dump,搞清签名到底放在哪个字段。不猜,看真实返回。
"""
import json
from sign import load_sdk

# 仿真一组 webcast wss 查询参数(值是占位,先看返回结构)
SAMPLE_PARAMS = {
    "app_name": "douyin_web",
    "version_code": "180800",
    "webcast_sdk_version": "1.0.14-beta.0",
    "room_id": "7659849144554572595",
    "sub_room_id": "",
    "sub_channel_id": "",
    "did_rule": "3",
    "user_unique_id": "7300000000000000000",
    "device_platform": "web",
    "device_type": "",
    "ac": "",
    "identity": "audience",
    "aid": "6383",
    "live_id": "1",
}


def main():
    out = {"stage": "start"}
    try:
        ctx = load_sdk()
        out["stage"] = "sdk_loaded"

        # 把参数注入 JS,尝试两种常见调用形态,分别 dump 返回
        ctx.eval("var __p = " + json.dumps(SAMPLE_PARAMS) + ";")

        # 形态一:直接把参数对象传给 frontierSign
        r1 = ctx.eval(r"""
        (function(){
          try {
            var r = window.byted_acrawler.frontierSign(__p);
            return JSON.stringify({ok:true, type:typeof r, val:r});
          } catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
        })();
        """)
        out["call_with_params"] = json.loads(r1)

        # 形态二:传 {"X-MS-STUB": <md5>} 形式
        r2 = ctx.eval(r"""
        (function(){
          try {
            var r = window.byted_acrawler.frontierSign({"X-MS-STUB":"00000000000000000000000000000000"});
            return JSON.stringify({ok:true, type:typeof r, val:r});
          } catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
        })();
        """)
        out["call_with_stub"] = json.loads(r2)

        out["stage"] = "done"
    except Exception as e:
        out["error_type"] = type(e).__name__
        out["error"] = str(e)[:800]
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
