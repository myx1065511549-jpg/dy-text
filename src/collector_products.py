"""商品采集(登录态):在已登录的 Playwright page 里 fetch 抖音商品列表接口。

关键:不自己逆向 a_bogus 签名。在登录态 page 上下文里 fetch,抖音自己的签名 SDK
(window.byted_acrawler)会自动补上 a_bogus + msToken。headless 登录态就能拿。
接口:POST /live/promotions/page/ 返回 promotions[] 全场商品(id/名/价/序号)。

本模块只做 URL 构造 + fetch + 解析,不管浏览器生命周期(由 collector_browser 提供 page)。
"""
import json

# 浏览器指纹类公共参数(与房间/登录无关的常量),room_id/author_id 及 webid/uifid 运行时补
_FINGERPRINT = {
    "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
    "update_version_code": "170400", "pc_client_type": "1", "pc_libra_divert": "Windows",
    "support_h265": "1", "support_dash": "0", "cpu_core_num": "12",
    "version_code": "320100", "version_name": "32.1.0", "cookie_enabled": "true",
    "screen_width": "1360", "screen_height": "900", "browser_language": "zh-CN",
    "browser_platform": "Win32", "browser_name": "Chrome", "browser_version": "120.0.0.0",
    "browser_online": "true", "engine_name": "Blink", "engine_version": "120.0.0.0",
    "os_name": "Windows", "os_version": "10", "device_memory": "32", "platform": "PC",
    "downlink": "1.45", "effective_type": "3g", "round_trip_time": "1000",
}

# 从进房请求里捞会话参数(webid/uifid),补进商品请求提高成功率
_SESSION_KEYS = ("webid", "uifid")


def build_page_url(room_id, author_id, base_params=None, offset=0, limit=50):
    """构造 /live/promotions/page/ 的完整 query(不含 a_bogus/msToken,由 SDK 补)。"""
    from urllib.parse import urlencode
    q = dict(_FINGERPRINT)
    if base_params:
        for k in _SESSION_KEYS:
            if base_params.get(k):
                q[k] = base_params[k]
    q.update({"room_id": str(room_id), "author_id": str(author_id),
              "offset": str(offset), "limit": str(limit)})
    return "https://live.douyin.com/live/promotions/page/?" + urlencode(q)


def parse_promotions(data):
    """从接口响应(dict)提取商品列表 -> [{product_id, promotion_id, title, price, idx, cover}]。
    price 为分(16800=¥168)。"""
    if not isinstance(data, dict):
        return []
    out = []
    for pr in data.get("promotions") or []:
        if not isinstance(pr, dict):
            continue
        pid = pr.get("product_id") or pr.get("promotion_id")
        if not pid:
            continue
        cover = None
        cov = pr.get("cover")
        if isinstance(cov, dict):
            urls = cov.get("url_list") or []
            cover = urls[0] if urls else None
        out.append({
            "product_id": str(pid),
            "promotion_id": str(pr.get("promotion_id") or pid),
            "title": pr.get("title") or pr.get("elastic_title") or "",
            "price": pr.get("min_price") or pr.get("price") or 0,
            "idx": pr.get("index") or pr.get("real_index") or 0,
            "cover": cover,
        })
    return out


# 在 page 上下文里发 fetch:登录态 cookie 自动带,byted_acrawler 自动补签名
_FETCH_JS = """
async ([url]) => {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'},
      body: ''
    });
    return {status: res.status, text: await res.text()};
  } catch (e) { return {status: -1, text: String(e).slice(0, 200)}; }
}
"""


def fetch_products(page, room_id, author_id, base_params=None, retries=2):
    """在登录态 page 里 fetch 商品列表,解析返回。偶发返空(网络抖动)时重试。
    返回 (products_list, ok)。ok=False 表示这次没取到(不覆盖已有字典)。"""
    if not room_id or not author_id:
        return [], False
    url = build_page_url(room_id, author_id, base_params)
    for attempt in range(retries + 1):
        try:
            r = page.evaluate(_FETCH_JS, [url])
        except Exception:
            r = None
        if r and r.get("status") == 200 and r.get("text"):
            try:
                data = json.loads(r["text"])
            except Exception:
                data = None
            if isinstance(data, dict) and data.get("promotions") is not None:
                return parse_promotions(data), True
        if attempt < retries:
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
    return [], False
