"""
天气查询服务 - Open-Meteo API (免费无需注册)
"""
import httpx
from typing import Optional, Dict, Any
from backend.logging_config import get_logger

logger = get_logger(__name__)


# WMO 天气代码转中文描述
WEATHER_CODE_MAP = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


class WeatherService:
    """天气查询服务 - Open-Meteo"""

    def __init__(self):
        self.geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        self.weather_url = "https://api.open-meteo.com/v1/forecast"

    async def _get_coordinates(self, city_name: str) -> Optional[Dict[str, Any]]:
        """
        根据城市名获取经纬度

        Args:
            city_name: 城市名称

        Returns:
            包含 latitude, longitude, name 的字典，失败返回 None
        """
        try:
            params = {
                "name": city_name,
                "count": 1,
                "language": "zh",
                "format": "json"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.geo_url, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("results"):
                    result = data["results"][0]
                    return {
                        "latitude": result["latitude"],
                        "longitude": result["longitude"],
                        "name": result.get("name", city_name),
                        "country": result.get("country", ""),
                        "timezone": result.get("timezone", "Asia/Shanghai")
                    }
                logger.warning("未找到城市: %s", city_name)
                return None

        except Exception as e:
            logger.warning("获取坐标失败: %s", e)
            return None

    async def get_weather(self, location: str) -> Optional[Dict[str, Any]]:
        """
        获取天气信息

        Args:
            location: 城市名称（如"上海"、"北京"、"苏州"）

        Returns:
            天气信息字典，失败返回 None
        """
        try:
            # 先获取城市坐标
            coords = await self._get_coordinates(location)
            if not coords:
                return None

            # 查询天气
            params = {
                "latitude": coords["latitude"],
                "longitude": coords["longitude"],
                "current_weather": True,
                "timezone": coords["timezone"]
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.weather_url, params=params)
                response.raise_for_status()
                data = response.json()

                weather = data.get("current_weather", {})
                weather_code = weather.get("weathercode", 0)
                wind_direction = weather.get("winddirection", 0)

                return {
                    "temp": weather.get("temperature", "N/A"),
                    "feelsLike": weather.get("temperature", "N/A"),  # Open-Meteo 没有体感温度
                    "text": WEATHER_CODE_MAP.get(weather_code, "未知"),
                    "windDir": self._get_wind_direction(wind_direction),
                    "windSpeed": weather.get("windspeed", "N/A"),
                    "location": coords["name"],
                    "country": coords.get("country", ""),
                    "code": weather_code,
                    "isDay": weather.get("is_day", 1)
                }

        except httpx.TimeoutException:
            logger.warning("请求超时")
            return None
        except httpx.HTTPStatusError as e:
            logger.error("HTTP错误: %s", e)
            return None
        except Exception as e:
            logger.error("未知错误: %s", e)
            return None

    async def get_daily_forecast(self, city: str) -> Optional[Dict[str, Any]]:
        """查询城市今明两天的逐日预报（穿衣建议/早晨提醒用）。

        Returns:
            {"city": 规范城市名, "country": ..., "today": {...}, "tomorrow": {...}}，
            其中每天含 date/temp_max/temp_min/precip_probability/precip_sum/weathercode/text。
            地理编码失败或数据不足返回 None。
        """
        coords = await self._get_coordinates(city)
        if not coords:
            return None
        params = {
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,weathercode",
            "timezone": coords["timezone"],
            "forecast_days": 2,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.weather_url, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.warning("获取逐日预报失败(%s): %s", city, e)
            return None

        daily = data.get("daily") or {}
        times = daily.get("time") or []
        if len(times) < 2:
            logger.warning("逐日预报数据不足(%s): %s", city, str(daily)[:200])
            return None
        prob_list = daily.get("precipitation_probability_max") or [0] * len(times)

        def _day(idx: int) -> Dict[str, Any]:
            code = (daily.get("weathercode") or [0] * len(times))[idx]
            return {
                "date": times[idx],
                "temp_max": (daily.get("temperature_2m_max") or [None] * len(times))[idx],
                "temp_min": (daily.get("temperature_2m_min") or [None] * len(times))[idx],
                "precip_probability": prob_list[idx] or 0,
                "precip_sum": (daily.get("precipitation_sum") or [0] * len(times))[idx] or 0,
                "weathercode": code,
                "text": WEATHER_CODE_MAP.get(code, "未知"),
            }

        return {
            "city": coords["name"],
            "country": coords.get("country", ""),
            "timezone": coords["timezone"],
            "today": _day(0),
            "tomorrow": _day(1),
        }

    def _get_wind_direction(self, degrees: int) -> str:
        """将角度转换为风向描述"""
        directions = [
            "北风", "东北偏北", "东北风", "东北偏东",
            "东风", "东南偏东", "东南风", "东南偏南",
            "南风", "西南偏南", "西南风", "西南偏西",
            "西风", "西北偏西", "西北风", "西北偏北"
        ]
        index = round(degrees / 22.5) % 16
        return directions[index]

    async def query_weather_tool(self, location: str = "北京") -> str:
        """
        工具调用接口 - 供 Agent 调用

        Args:
            location: 城市名称，如"北京"、"苏州"、"上海"等

        Returns:
            格式化的天气信息字符串
        """
        weather = await self.get_weather(location)
        if weather:
            return self.format_weather_for_pet(weather)
        return f"抱歉，查不到 {location} 的天气信息..."

    def format_weather_for_pet(self, weather: Dict[str, Any]) -> str:
        """
        将天气信息格式化为宠物友好的描述

        Args:
            weather: 天气信息字典

        Returns:
            格式化的天气描述
        """
        if not weather:
            return "鼠鼠查不到天气信息..."

        location = weather.get("location", "")
        temp = weather.get("temp", "N/A")
        text = weather.get("text", "未知")
        wind_dir = weather.get("windDir", "")
        wind_speed = weather.get("windSpeed", "N/A")

        day_night = "白天" if weather.get("isDay") == 1 else "夜晚"
        country = weather.get("country", "")
        if country:
            location_str = f"{location}({country})"
        else:
            location_str = location

        return f"{location_str}{day_night}{text}，温度{temp}°C，{wind_dir}，风速{wind_speed}km/h"


# 全局单例
weather_service = WeatherService()


def evaluate_weather_significance(today: Optional[Dict[str, Any]], tomorrow: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """判断次日天气是否「显著」到值得主动提醒。

    规则（满足任一即显著）：
    - 降水概率 >= 40%                          -> "rain"（气泡提示带伞）
    - 24h 降温：今日最高温 - 明日最高温 >= 5°C  -> "cooling"
    - 明日最高温 >= 33°C                       -> "hot"
    - 明日最低温 <= 0°C                        -> "cold"

    返回 (是否显著, 原因键)；不显著时原因键为 None。
    """
    precip_prob = tomorrow.get("precip_probability") or 0
    if precip_prob >= 40:
        return True, "rain"
    tmax = tomorrow.get("temp_max")
    if tmax is not None:
        today_max = (today or {}).get("temp_max")
        if today_max is not None and today_max - tmax >= 5:
            return True, "cooling"
        if tmax >= 33:
            return True, "hot"
    tmin = tomorrow.get("temp_min")
    if tmin is not None and tmin <= 0:
        return True, "cold"
    return False, None


def build_outfit_advice(tomorrow: Dict[str, Any]) -> str:
    """无 LLM 可用时的模板穿衣建议：按最高温五档 + 降水附加提示。"""
    tmax = tomorrow.get("temp_max")
    tmin = tomorrow.get("temp_min")
    prob = tomorrow.get("precip_probability") or 0
    precip_sum = tomorrow.get("precip_sum") or 0
    text = tomorrow.get("text") or "未知"

    if tmax is None:
        base = "明天的天气有点多变，洋葱式穿衣最稳妥，方便随时增减～"
    elif tmax >= 33:
        base = f"明天最高{tmax:g}°C，热浪来袭：短袖短裤安排上，记得防晒多补水～"
    elif tmax >= 25:
        base = f"明天最高{tmax:g}°C，轻薄透气的夏装最合适，长时间在空调房可以备件薄外套～"
    elif tmax >= 15:
        lo = f"，最低{tmin:g}°C" if tmin is not None else ""
        base = f"明天{tmax:g}°C{lo}，长袖加一件薄外套，冷热切换都不怕～"
    elif tmax >= 5:
        lo = f"，最低{tmin:g}°C" if tmin is not None else ""
        base = f"明天{tmax:g}°C{lo}，凉意明显：毛衣或厚夹克穿起来，早晚注意保暖～"
    else:
        base = f"明天最高才{tmax:g}°C，冻手冻脚：羽绒服/厚棉衣全副武装，围巾也别落下～"

    if prob >= 40 or precip_sum >= 1:
        base += f" 另外明天有雨（降水概率{prob:g}%），出门记得带伞☔"
    return base
