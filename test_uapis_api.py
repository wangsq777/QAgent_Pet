"""
测试 uapis.cn 天气 API
"""
import httpx
import asyncio
import json

async def test_uapis_weather():
    print("=" * 50)
    print("uapis.cn 天气 API 测试")
    print("=" * 50)
    
    # 尝试常见的 API 格式
    test_urls = [
        # 格式1: 基础天气
        ("基础格式", "https://uapis.cn/api/weather?city=上海"),
        ("基础格式北京", "https://uapis.cn/api/weather?city=北京"),
        # 格式2: 带key
        ("带key参数", "https://uapis.cn/api/weather?city=上海&key=test"),
        # 格式3: 其他常见格式
        ("免费天气", "https://uapis.cn/free/weather?city=上海"),
        ("v1版本", "https://uapis.cn/v1/weather?city=上海"),
    ]
    
    for name, url in test_urls:
        print(f"\n>>> 测试: {name}")
        print(f"URL: {url}")
        
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                print(f"状态码: {response.status_code}")
                print(f"响应: {response.text[:500]}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"[OK] JSON响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
                    except:
                        pass
                        
        except Exception as e:
            print(f"[FAIL] 异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_uapis_weather())
