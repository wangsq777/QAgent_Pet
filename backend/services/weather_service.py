"""
天气查询服务 - Open-Meteo API (免费无需注册)
"""
import httpx
from typing import Optional, Dict, Any


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
                print(f"[Weather] 未找到城市: {city_name}")
                return None

        except Exception as e:
            print(f"[Weather] 获取坐标失败: {e}")
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
            print("[Weather] 请求超时")
            return None
        except httpx.HTTPStatusError as e:
            print(f"[Weather] HTTP错误: {e}")
            return None
        except Exception as e:
            print(f"[Weather] 未知错误: {e}")
            return None

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
