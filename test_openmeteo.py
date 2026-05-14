"""
测试 Open-Meteo 天气 API
"""
import httpx
import asyncio
import json

async def test_open_meteo():
    print("=" * 50)
    print("Open-Meteo 天气 API 测试")
    print("=" * 50)

    # 测试1：直接用经纬度查询天气
    print("\n>>> 测试1: 经纬度查询天气（上海）")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 31.23,
        "longitude": 121.47,
        "current_weather": True,
        "timezone": "Asia/Shanghai"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        print(f"状态码: {response.status_code}")
        data = response.json()
        print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
    
    # 测试2：城市名转经纬度
    print("\n>>> 测试2: 城市名转经纬度（苏州）")
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    geo_params = {
        "name": "苏州",
        "count": 1,
        "language": "zh",
        "format": "json"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(geo_url, params=geo_params)
        print(f"状态码: {response.status_code}")
        geo_data = response.json()
        print(f"响应: {json.dumps(geo_data, ensure_ascii=False, indent=2)}")
        
        if geo_data.get("results"):
            result = geo_data["results"][0]
            lat = result["latitude"]
            lon = result["longitude"]
            city_name = result["name"]
            print(f"\n[OK] 找到城市: {city_name}, 经纬度: ({lat}, {lon})")
            
            # 用找到的经纬度查询天气
            print(f"\n>>> 测试3: 查询 {city_name} 天气")
            weather_params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
                "timezone": "Asia/Shanghai"
            }
            response = await client.get(url, params=weather_params)
            weather = response.json()
            cw = weather.get("current_weather", {})
            print(f"[OK] {city_name} 当前天气:")
            print(f"  - 温度: {cw.get('temperature')}°C")
            print(f"  - 风速: {cw.get('windspeed')} km/h")
            print(f"  - 天气代码: {cw.get('weathercode')}")
            print(f"  - 时间: {cw.get('time')}")

asyncio.run(test_open_meteo())
