# -*- coding: utf-8 -*-
"""肥鱼科研版的天气查询模块 —— 多数据源 + 自动降级。

为什么要单独一个文件：
  - 主程序已经 1400+ 行，天气逻辑塞进去会越来越乱
  - 天气数据源随时可能变（中国天气网的老接口就废弃了），
    独立成模块后换源只改这里，不动主程序

数据源（按优先级自动降级）：
  1. 中国天气网 d1.weather.com.cn  —— 官方、免 key、国内最快（实测 200ms）
  2. Open-Meteo                    —— 国际源，免 key，作为备用
  3. wttr.in                       —— 原程序用的，最慢，最后兜底

用法：
    from weather_api import query_weather, resolve_city, WeatherError
    result = query_weather("北京", include_forecast=True)
    print(result.summary())
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "http://www.weather.com.cn/",
}

# 网络超时（秒）。国内源很快，给 8 秒足够；国际源宽松一点。
TIMEOUT_CN = 8
TIMEOUT_INTL = 12


class WeatherError(Exception):
    """取天气失败，message 是可以直接显示给用户的中文说明。"""


# --------------------------------------------------------------------------
# 城市 → 中国天气网城市代码
# 代码是 9 位数字（如北京 101010100）。这里内置常用城市，
# 找不到时再走一次在线搜索。
# --------------------------------------------------------------------------
CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "天津": "101030100", "重庆": "101040100",
    "哈尔滨": "101050101", "长春": "101060101", "沈阳": "101070101", "呼和浩特": "101080101",
    "石家庄": "101090101", "太原": "101100101", "西安": "101110101", "济南": "101120101",
    "乌鲁木齐": "101130101", "拉萨": "101140101", "西宁": "101150101", "兰州": "101160101",
    "银川": "101170101", "郑州": "101180101", "南京": "101190101", "武汉": "101200101",
    "杭州": "101210101", "合肥": "101220101", "福州": "101230101", "南昌": "101240101",
    "长沙": "101250101", "贵阳": "101260101", "成都": "101270101", "广州": "101280101",
    "深圳": "101280601", "珠海": "101280701", "东莞": "101281601", "佛山": "101280800",
    "汕头": "101280501", "南宁": "101300101", "海口": "101310101", "三亚": "101310201",
    "香港": "101320101", "澳门": "101330101", "台北": "101340101",
    # 直辖市/省会之外的常见城市
    "苏州": "101190401", "无锡": "101190201", "宁波": "101210401", "温州": "101210701",
    "青岛": "101120201", "大连": "101070201", "厦门": "101230201", "泉州": "101230501",
    "徐州": "101190801", "常州": "101191101", "南通": "101190501", "扬州": "101190601",
    "洛阳": "101180901", "烟台": "101120501", "潍坊": "101120601", "淄博": "101120301",
    "中山": "101281701", "惠州": "101280301", "江门": "101281101", "湛江": "101281001",
    "桂林": "101300501", "柳州": "101300301", "遵义": "101260201", "绵阳": "101270401",
}
# 英文名 / 拼音也能查（Open-Meteo 需要经纬度，中国天气网需要代码，两边都用得上）
CITY_ALIASES = {
    "beijing": "北京", "shanghai": "上海", "tianjin": "天津", "chongqing": "重庆",
    "guangzhou": "广州", "shenzhen": "深圳", "shantou": "汕头", "hangzhou": "杭州",
    "nanjing": "南京", "wuhan": "武汉", "chengdu": "成都", "xian": "西安", "xi'an": "西安",
    "suzhou": "苏州", "qingdao": "青岛", "dalian": "大连", "xiamen": "厦门",
    "changsha": "长沙", "zhengzhou": "郑州", "jinan": "济南", "shenyang": "沈阳",
    "harbin": "哈尔滨", "kunming": "昆明", "guiyang": "贵阳", "nanning": "南宁",
    "haikou": "海口", "sanya": "三亚", "hongkong": "香港", "hong kong": "香港",
    "taipei": "台北", "lhasa": "拉萨", "urumqi": "乌鲁木齐",
}
# 供 Open-Meteo 兜底用的大致经纬度（只覆盖常用城市，够用）
CITY_COORDS = {
    "北京": (39.90, 116.41), "上海": (31.23, 121.47), "天津": (39.13, 117.20),
    "重庆": (29.56, 106.55), "广州": (23.13, 113.26), "深圳": (22.54, 114.06),
    "汕头": (23.35, 116.68), "杭州": (30.27, 120.16), "南京": (32.06, 118.80),
    "武汉": (30.59, 114.31), "成都": (30.57, 104.07), "西安": (34.34, 108.94),
    "苏州": (31.30, 120.62), "青岛": (36.07, 120.38), "大连": (38.91, 121.61),
    "厦门": (24.48, 118.09), "长沙": (28.23, 112.94), "郑州": (34.75, 113.63),
    "济南": (36.65, 117.12), "沈阳": (41.81, 123.43), "哈尔滨": (45.80, 126.53),
    "昆明": (24.88, 102.83), "贵阳": (26.65, 106.63), "南宁": (22.82, 108.32),
    "海口": (20.04, 110.32), "三亚": (18.25, 109.51), "香港": (22.32, 114.17),
    "台北": (25.03, 121.57), "拉萨": (29.65, 91.14), "乌鲁木齐": (43.83, 87.62),
}

# 天气现象代码 → 中文（中国天气网 fa/fb 字段）
WEATHER_CODE_CN = {
    "00": "晴", "01": "多云", "02": "阴", "03": "阵雨", "04": "雷阵雨",
    "05": "雷阵雨伴有冰雹", "06": "雨夹雪", "07": "小雨", "08": "中雨",
    "09": "大雨", "10": "暴雨", "11": "大暴雨", "12": "特大暴雨",
    "13": "阵雪", "14": "小雪", "15": "中雪", "16": "大雪", "17": "暴雪",
    "18": "雾", "19": "冻雨", "20": "沙尘暴", "21": "小到中雨", "22": "中到大雨",
    "23": "大到暴雨", "24": "暴雨到大暴雨", "25": "大暴雨到特大暴雨",
    "26": "小到中雪", "27": "中到大雪", "28": "大到暴雪", "29": "浮尘",
    "30": "扬沙", "31": "强沙尘暴", "53": "霾",
    # wttr.in / Open-Meteo 的英文描述也一起映射，省得各写一套
    "Sunny": "晴", "Clear": "晴", "Partly cloudy": "多云", "Cloudy": "阴",
    "Overcast": "阴", "Mist": "雾", "Fog": "雾", "Light rain": "小雨",
    "Moderate rain": "中雨", "Heavy rain": "大雨", "Light snow": "小雪",
    "Moderate snow": "中雪", "Heavy snow": "大雪",
    "Thundery outbreaks possible": "雷阵雨",
}


def resolve_city(name: str):
    """城市名 → (中文规范名, 中国天气网代码, (纬度, 经度) 或 None)。

    识别不了时返回 (原名, None, None)，让调用方决定怎么办。
    空输入返回 (None, None, None) —— 由调用方报错，不要悄悄用默认城市。
    """
    raw = (name or "").strip()
    if not raw:
        return None, None, None

    key = raw.lower().replace("市", "").replace(" ", "")
    if key in CITY_ALIASES:
        cn = CITY_ALIASES[key]
        return cn, CITY_CODES.get(cn), CITY_COORDS.get(cn)

    cn = raw.replace("市", "").strip()
    if cn in CITY_CODES:
        return cn, CITY_CODES[cn], CITY_COORDS.get(cn)

    # 子串匹配：比如「朝阳区」→「北京」这种做不到，但「北京市朝阳区」能匹配上北京
    for city, code in CITY_CODES.items():
        if city in cn:
            return city, code, CITY_COORDS.get(city)

    # 纯数字：当作中国天气网城市代码直接用
    if re.fullmatch(r"\d{9}", cn):
        return cn, cn, None

    return raw, None, None


# --------------------------------------------------------------------------
# 数据载体
# --------------------------------------------------------------------------
@dataclass
class DailyForecast:
    label: str          # 今天 / 明天 / 周三
    date: str           # 10/06
    weather: str        # 晴
    temp_high: str      # 24
    temp_low: str       # 11
    wind: str           # 北风转西南风 <3级


@dataclass
class WeatherResult:
    ok: bool
    city: str
    source: str                       # 哪个数据源给的
    error: str = ""

    # 实时
    temp: str = ""
    feels_like: str = ""
    weather: str = ""
    wind: str = ""
    humidity: str = ""
    rain: str = ""
    aqi: str = ""
    aqi_level: str = ""
    limit: str = ""                   # 限行
    updated: str = ""

    # 今天
    today_high: str = ""
    today_low: str = ""

    # 附加
    forecast: list = field(default_factory=list)   # List[DailyForecast]
    alerts: list = field(default_factory=list)     # 预警标题
    tips: list = field(default_factory=list)       # 生活指数提示

    def summary(self) -> str:
        """一句话播报，用于桌宠气泡。"""
        if not self.ok:
            return self.error or "天气获取失败"
        bits = [f"{self.city} {self.weather} {self.temp}°C"]
        if self.today_high and self.today_low:
            bits.append(f"（{self.today_low}~{self.today_high}°C）")
        if self.wind:
            bits.append(self.wind)
        if self.aqi:
            bits.append(f"空气{self.aqi}")
        return " ".join(bits)

    def compact(self) -> str:
        """极简版报告：固定 2-3 行，用于肥鱼头顶的气泡面板。

        完整报告有 20 多行、近 380px 高。这个版本约 3 行（约 90px），
        高度只有完整版约 1/4，宽度不变。

        行结构：
          1. 【城市】天气 现在温度　今日区间
          2. 风力　湿度　空气质量　限行
          3. 未来两天（跳过"今天"—— 第一行已经报了今日区间，重复显示没意义）
          4. 预警（有才显示）
        """
        if not self.ok:
            return self.error or "天气获取失败"

        L = []
        # 第 1 行：城市 + 现在 + 今日区间
        head = f"【{self.city}】{self.weather} {self.temp}°C"
        if self.today_high or self.today_low:
            head += f"　{self.today_low}~{self.today_high}°C"
        L.append(head)

        # 第 2 行：风力 / 湿度 / 空气 / 限行（挤一行）
        bits = []
        if self.wind:
            bits.append(self.wind)
        if self.humidity:
            bits.append(f"湿度{self.humidity}")
        if self.aqi:
            bits.append(f"空气{self.aqi}")
        if self.limit and self.limit not in ("不限行",):
            bits.append(self.limit)
        if bits:
            L.append("　".join(bits))

        # 第 3 行：未来两天。
        # 跳过 index 0（今天）—— 上面第一行已经给了今日区间，
        # 再列一遍「今天 晴11~24°」是重复信息。
        upcoming = [d for d in self.forecast if d.label != "今天"]
        if not upcoming and self.forecast:
            upcoming = self.forecast[1:]          # 兜底：按位置跳过第一天

        if upcoming:
            def short(label):
                # 「星期三」-> 「周三」，省地方
                return label.replace("星期", "周")
            cells = [f"{short(d.label)} {d.weather}{d.temp_low}~{d.temp_high}°"
                     for d in upcoming[:2]]
            L.append("　".join(cells))

        # 第 4 行：有预警才加
        if self.alerts:
            L.append(f"⚠️ {self.alerts[0]}")

        return "\n".join(L)

    def report(self) -> str:
        """多行详细汇报，用于聊天窗口。"""
        if not self.ok:
            return self.error or "天气获取失败"
        L = [f"【{self.city} 天气】数据来源：{self.source}"]
        now = f"实时 {self.temp}°C"
        if self.feels_like:
            now += f"（体感 {self.feels_like}°C）"
        if self.weather:
            now += f"  {self.weather}"
        L.append(now)
        if self.today_high or self.today_low:
            L.append(f"今日 {self.today_low}~{self.today_high}°C")
        detail = []
        if self.wind:
            detail.append(self.wind)
        if self.humidity:
            detail.append(f"湿度{self.humidity}")
        if self.rain:
            detail.append(f"降水{self.rain}mm")
        if detail:
            L.append("  ".join(detail))
        if self.aqi:
            L.append(f"空气质量 AQI {self.aqi}" + (f"（{self.aqi_level}）" if self.aqi_level else ""))
        if self.limit:
            L.append(f"限行：{self.limit}")
        if self.alerts:
            L.append("")
            L.append("⚠️ 预警：")
            for a in self.alerts[:3]:
                L.append(f"  · {a}")
        if self.forecast:
            L.append("")
            L.append("未来几天：")
            for d in self.forecast[:7]:
                L.append(f"  {d.label:4} {d.weather:6} {d.temp_low}~{d.temp_high}°C  {d.wind}")
        if self.tips:
            L.append("")
            L.append("生活提示：")
            for t in self.tips[:5]:
                L.append(f"  · {t}")
        if self.updated:
            L.append("")
            L.append(f"（数据更新时间 {self.updated}）")
        return "\n".join(L)


# --------------------------------------------------------------------------
# 数据源 1：中国天气网（官方、免 key、最快）
# --------------------------------------------------------------------------
def _cn_decode(resp) -> str:
    """中国天气网的 d1 接口是 GBK，但 HTTP 头常声明 utf-8。

    直接用 resp.text 会得到乱码（"鍖椾含"），需要把已解码的字符串还原成
    字节再按 GBK 解一次。
    """
    text = resp.content.decode("utf-8", errors="replace")
    try:
        repaired = text.encode("latin-1").decode("gbk")
        # 修补后中文更多就用修补结果，否则说明本来就没错
        if sum(1 for c in repaired if "\u4e00" <= c <= "\u9fff") > \
           sum(1 for c in text if "\u4e00" <= c <= "\u9fff"):
            return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def _cn_var(text: str, name: str):
    """取 `var name = {...}` 里的 JSON。

    不能用简单的 `\\{.*?\\}` 正则：这些段里有嵌套对象，
    而且最后一段（fc）没有结尾分号。所以做一次花括号配对。
    """
    m = re.search(rf'var\s+{name}\s*=\s*', text)
    if not m:
        return None
    start = text.find('{', m.end())
    if start < 0:
        return None

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def _aqi_level(aqi) -> str:
    try:
        v = int(float(aqi))
    except (TypeError, ValueError):
        return ""
    for limit, label in ((50, "优"), (100, "良"), (150, "轻度污染"),
                         (200, "中度污染"), (300, "重度污染")):
        if v <= limit:
            return label
    return "严重污染"


def fetch_china_weather(city: str, code: str, want_forecast: bool = True) -> WeatherResult:
    url = f"http://d1.weather.com.cn/weather_index/{code}.html"
    resp = requests.get(url, timeout=TIMEOUT_CN, headers=UA)
    resp.raise_for_status()
    text = _cn_decode(resp)

    sk = _cn_var(text, "dataSK") or {}
    dz = (_cn_var(text, "cityDZ") or {}).get("weatherinfo", {}) or {}
    alarms = (_cn_var(text, "alarmDZ") or {}).get("w", []) or []

    if not sk and not dz:
        raise WeatherError("中国天气网返回内容为空（该城市代码可能已失效）")

    res = WeatherResult(ok=True, city=sk.get("cityname") or dz.get("city") or city,
                        source="中国天气网")
    res.temp = str(sk.get("temp", "")).strip()
    # 气温用整数显示：源返回 24.6 这种小数时，跟预报的整数（24）放一起会显得
    # 精度不一致（「今日 11~24.6°C」看着很怪）。
    try:
        res.temp = str(int(round(float(res.temp))))
    except (TypeError, ValueError):
        pass
    res.weather = sk.get("weather") or dz.get("weather") or ""
    wd, ws = sk.get("WD", ""), sk.get("WS", "")
    res.wind = f"{wd}{ws}".strip()
    res.humidity = str(sk.get("SD", "")).strip()
    rain = str(sk.get("rain", "")).strip()
    res.rain = rain if rain not in ("", "0", "0.0") else ""
    res.aqi = str(sk.get("aqi", "")).strip()
    res.aqi_level = _aqi_level(res.aqi)
    res.limit = str(sk.get("limitnumber", "")).strip()
    t = str(sk.get("time", "")).strip()
    d = str(sk.get("date", "")).strip()
    res.updated = f"{d} {t}".strip()
    res.today_high = str(dz.get("temp", "")).strip()
    res.today_low = str(dz.get("tempn", "")).strip()
    # 预警
    for a in alarms:
        if isinstance(a, dict):
            txt = a.get("w1") or a.get("title") or ""
            if txt:
                res.alerts.append(str(txt))

    # 7 日预报（fc.f 数组）
    try:
        fc = _cn_var(text, "fc") or {}
        for day in fc.get("f", [])[:7]:
            hi = str(day.get("fc", "")).strip()
            lo = str(day.get("fd", "")).strip()
            w = WEATHER_CODE_CN.get(str(day.get("fa", "")), "") or str(day.get("fa", ""))
            wd1, wd2 = day.get("fe", ""), day.get("ff", "")
            wind = f"{wd1}转{wd2}" if wd1 and wd2 and wd1 != wd2 else (wd1 or wd2)
            lvl = day.get("fg", "")
            res.forecast.append(DailyForecast(
                label=str(day.get("fj", "")).strip(),
                date=str(day.get("fi", "")).strip(),
                weather=w,
                temp_high=hi,
                temp_low=lo,
                wind=f"{wind} {lvl}".strip(),
            ))
    except (ValueError, AttributeError, KeyError):
        pass

    # 生活指数（扁平结构：xx_name / xx_hint / xx_des_s）
    try:
        zs = (_cn_var(text, "dataZS") or {}).get("zs", {})
        if isinstance(zs, dict):
            for k, v in zs.items():
                if k.endswith("_name") and v:
                    prefix = k[:-5]
                    hint = zs.get(f"{prefix}_hint", "")
                    if hint:
                        res.tips.append(f"{v}：{hint}")
    except (ValueError, AttributeError):
        pass

    # 今日高低温：两个源会给出不同答案，规则是「谁和实时温度自洽就用谁」。
    #   北京实测：实时 24.6°C，cityDZ 说 15~17（明显过时），fc 说 11~24（合理）-> 用 fc
    #   汕头实测：实时 26.2°C，cityDZ 说 24~26（合理），fc 说 22~29（偏低）-> 用 cityDZ
    # 只信一个源会得到「今日最高 17°C 但现在 24.6°C」这种怪话。
    #
    # 必须放在清除 forecast 之前：fc 和 dataSK 来自同一个 HTTP 响应，
    # 解析它不额外花时间，want_forecast 只决定最后要不要返回列表。
    try:
        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        cur = _f(res.temp)
        dz_hi, dz_lo = _f(res.today_high), _f(res.today_low)
        fc = res.forecast[0] if res.forecast else None
        fc_hi, fc_lo = (_f(fc.temp_high), _f(fc.temp_low)) if fc else (None, None)

        def coherent(hi, lo):
            """区间是否自洽：低不高过高，且当前温度没超出区间太多。

            容差 1.5°C：两个数据源一个是小数一个是整数，边界差 1 度以内属正常舍入。
            """
            if hi is None or lo is None or lo > hi:
                return False
            if cur is not None and cur > hi + 1.5:
                return False
            return True

        if coherent(dz_hi, dz_lo):
            # cityDZ 自洽，采信它；当前温度略高于它报的高温时，把高温抬到当前温度
            if cur is not None and cur > dz_hi:
                res.today_high = str(int(round(cur)))
        elif coherent(fc_hi, fc_lo):
            res.today_high = fc.temp_high
            res.today_low = fc.temp_low
            if cur is not None and fc_hi is not None and cur > fc_hi:
                res.today_high = str(int(round(cur)))
        else:
            # 两个源都不可信（或缺数据）-> 干脆不显示区间，好过显示错的
            res.today_high = ""
            res.today_low = ""
    except (TypeError, ValueError):
        pass

    # 一致性算完再决定要不要保留预报列表
    if not want_forecast:
        res.forecast = []
    return res


# --------------------------------------------------------------------------
# 数据源 2：Open-Meteo（免 key，国际源，作备用）
# --------------------------------------------------------------------------
OPEN_METEO_CODES = {
    0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨", 56: "冻毛毛雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴伴冰雹",
}


def fetch_open_meteo(city: str, coords, want_forecast: bool = True) -> WeatherResult:
    if not coords:
        raise WeatherError("Open-Meteo 需要城市经纬度，但内置表里没有这个城市")
    lat, lon = coords
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "weather_code,wind_speed_10m,wind_direction_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "wind_speed_10m_max,wind_direction_10m_dominant",
            "timezone": "Asia/Shanghai",
            "forecast_days": 7,
        },
        timeout=TIMEOUT_INTL,
        headers={"User-Agent": UA["User-Agent"]},
    )
    resp.raise_for_status()
    data = resp.json()

    cur = data.get("current", {})
    res = WeatherResult(ok=True, city=city, source="Open-Meteo")
    res.temp = str(round(cur.get("temperature_2m", 0), 1))
    res.feels_like = str(round(cur.get("apparent_temperature", 0), 1))
    res.weather = OPEN_METEO_CODES.get(cur.get("weather_code"), "")
    res.humidity = f"{cur.get('relative_humidity_2m', '')}%"
    res.wind = f"{cur.get('wind_direction_10m', '')}° {cur.get('wind_speed_10m', '')}km/h"
    p = cur.get("precipitation", 0)
    res.rain = str(p) if p else ""
    res.updated = str(cur.get("time", "")).replace("T", " ")

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    codes = daily.get("weather_code", [])
    his = daily.get("temperature_2m_max", [])
    los = daily.get("temperature_2m_min", [])
    winds = daily.get("wind_speed_10m_max", [])

    if dates:
        res.today_high = str(round(his[0], 1)) if his else ""
        res.today_low = str(round(los[0], 1)) if los else ""

    if want_forecast:
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for i, dt in enumerate(dates[:7]):
            label = "今天" if i == 0 else ("明天" if i == 1 else "")
            if not label:
                try:
                    import datetime as _dt
                    label = weekday[_dt.date.fromisoformat(dt).weekday()]
                except (ValueError, TypeError):
                    label = dt
            res.forecast.append(DailyForecast(
                label=label, date=dt[5:],
                weather=OPEN_METEO_CODES.get(codes[i] if i < len(codes) else None, ""),
                temp_high=str(round(his[i])) if i < len(his) else "",
                temp_low=str(round(los[i])) if i < len(los) else "",
                wind=f"{round(winds[i])}km/h" if i < len(winds) else "",
            ))
    return res


# --------------------------------------------------------------------------
# 数据源 3：wttr.in（原程序用的，最慢，兜底）
# --------------------------------------------------------------------------
def fetch_wttr(city: str, want_forecast: bool = True) -> WeatherResult:
    resp = requests.get(f"https://wttr.in/{city}?format=j1",
                        timeout=TIMEOUT_INTL, headers={"User-Agent": UA["User-Agent"]})
    resp.raise_for_status()
    data = resp.json()
    cur = data["current_condition"][0]

    res = WeatherResult(ok=True, city=city, source="wttr.in")
    res.temp = str(cur.get("temp_C", ""))
    res.feels_like = str(cur.get("FeelsLikeC", ""))
    raw = cur.get("weatherDesc", [{}])[0].get("value", "")
    res.weather = WEATHER_CODE_CN.get(raw, raw)
    res.humidity = f"{cur.get('humidity', '')}%"
    res.wind = f"{cur.get('winddir16Point', '')} {cur.get('windspeedKmph', '')}km/h"
    res.updated = str(cur.get("localObsDateTime", ""))

    if want_forecast:
        for day in data.get("weather", [])[:7]:
            date = str(day.get("date", ""))
            label = "今天" if date == data["weather"][0].get("date") else date[5:]
            if day is data["weather"][0]:
                label = "今天"
            elif data.get("weather", []).index(day) == 1:
                label = "明天"
            desc = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "")
            res.forecast.append(DailyForecast(
                label=label, date=date[5:],
                weather=WEATHER_CODE_CN.get(desc, desc),
                temp_high=str(day.get("maxtempC", "")),
                temp_low=str(day.get("mintempC", "")),
                wind="",
            ))
        if res.forecast:
            res.today_high = res.forecast[0].temp_high
            res.today_low = res.forecast[0].temp_low
    return res


# --------------------------------------------------------------------------
# 对外入口：按优先级试，全部失败才报错
# --------------------------------------------------------------------------
def query_weather(city: str, want_forecast: bool = True,
                  prefer: Optional[str] = None) -> WeatherResult:
    """查天气。任何数据源成功就返回，全失败返回 ok=False 的结果。

    prefer: 强制指定数据源（"中国天气网" / "Open-Meteo" / "wttr.in"），
            默认按优先级自动降级。
    """
    cn_name, code, coords = resolve_city(city)

    if cn_name is None:
        return WeatherResult(ok=False, city="", source="",
                             error="没有指定城市。请在右键菜单里设置城市，"
                                   "或在参数里给出城市名（如「北京」）。")

    # 认不出的城市要直接报错，不能放任降级到 wttr.in ——
    # 那个接口什么字符串都收，会返回一个看似正常其实是错的天气。
    if code is None and coords is None and prefer is None:
        return WeatherResult(
            ok=False, city=cn_name, source="",
            error=(f"认不出城市「{city}」。\n"
                   f"可以试试：北京 / 上海 / 汕头 这样的中文城市名，"
                   f"或者 shanghai 这样的拼音，\n"
                   f"也可以直接填中国天气网的 9 位城市代码（如 101010100 = 北京）。"),
        )

    attempts = []
    if prefer == "中国天气网":
        attempts = [("cn",)]
    elif prefer == "Open-Meteo":
        attempts = [("intl",)]
    elif prefer == "wttr.in":
        attempts = [("wttr",)]
    else:
        attempts = [("cn",), ("intl",), ("wttr",)]

    errors = []
    for (kind,) in attempts:
        try:
            if kind == "cn":
                if not code:
                    errors.append("中国天气网：没有该城市的代码")
                    continue
                return fetch_china_weather(cn_name, code, want_forecast)
            if kind == "intl":
                return fetch_open_meteo(cn_name, coords, want_forecast)
            return fetch_wttr(cn_name, want_forecast)
        except WeatherError as e:
            errors.append(str(e))
        except requests.exceptions.Timeout:
            errors.append(f"{kind} 超时")
        except requests.exceptions.ConnectionError:
            errors.append(f"{kind} 连不上")
        except requests.exceptions.HTTPError as e:
            errors.append(f"{kind} HTTP {getattr(e.response, 'status_code', '?')}")
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"{kind} 数据格式异常: {str(e)[:40]}")
        except Exception as e:                       # 兜底，绝不让桌宠崩
            errors.append(f"{kind} {type(e).__name__}: {str(e)[:40]}")

    hint = ""
    if not code:
        hint = f"\n（认不出城市「{city}」，试试「北京」这样的城市名，或直接填 9 位城市代码）"
    return WeatherResult(
        ok=False, city=cn_name, source="", 
        error="天气查询失败：\n  " + "\n  ".join(errors) + hint,
    )


if __name__ == "__main__":
    # 命令行自测：python weather_api.py 北京
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "北京"
    t0 = time.time()
    r = query_weather(target)
    print(f"[{time.time()-t0:.2f}s]")
    print(r.report())
