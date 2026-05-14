"""
测试和风天气 API 连接
"""
import httpx
import asyncio
import json
from backend.config import settings

async def test_weather_api():
    api_key = settings.WEATHER_API_KEY
    print("=" * 50)
    print("和风天气 API 测试")
    print("=" * 50)
    print(f"API Key: {api_key[:10]}...{api_key[-4:] if len(api_key) > 14 else 'N/A'}")
    print(f"Base URL: https://api.qweather.com/v7/weather/now")
    print("-" * 50)
    
    # 测试城市列表
    test_locations = ["上海", "北京", "苏州", "101010100"]  # 包括城市名和城市代码
    
    for location in test_locations:
        url = "https://api.qweather.com/v7/weather/now"
        params = {
            "location": location,
            "key": api_key,
            "lang": "zh"
        }
        
        print(f"\n>>> 测试城市: {location}")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                print(f"状态码: {response.status_code}")
                
                try:
                    data = response.json()
                    print(f"响应内容: {json.dumps(data, ensure_ascii=False, indent=2)}")
                except:
                    print(f"原始响应: {response.text}")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == "200":
                        weather = data.get("now", {})
                        print(f"[OK] 城市: {data.get('location', {}).get('name')}")
                        print(f"[OK] 天气: {weather.get('text')}, 温度: {weather.get('temp')}C")
                    else:
                        print(f"[FAIL] API返回错误码: {data.get('code')}")
                        if "Invalid key" in str(data):
                            print("[FAIL] 原因: API Key 无效或过期")
                        elif "no data" in str(data).lower():
                            print("[FAIL] 原因: 城市不存在或不支持")
                else:
                    print(f"[FAIL] HTTP错误: {response.status_code}")
                    if response.status_code == 403:
                        print("[FAIL] 原因: 可能是 API Key 没有权限 / 额度用完 / 服务不支持该城市")
                    
        except httpx.TimeoutException:
            print("[FAIL] 请求超时")
        except Exception as e:
            print(f"[FAIL] 异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_weather_api())
