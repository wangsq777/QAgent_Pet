"""
IP地理位置服务 - 自动获取用户所在地区
"""
import httpx
from typing import Optional
import os


class IPLocationService:
    """
    通过 IP 地址获取用户地理位置
    支持多种数据源：
    1. 免费 API: ip-api.com (推荐，无需 API Key)
    2. HTTP 请求头中的 X-Forwarded-For (反向代理场景)
    """
    
    def __init__(self):
        self._cache: dict = {}
        self._cache_ttl = 3600  # 缓存1小时
    
    async def get_location_by_ip(self, client_ip: str) -> Optional[dict]:
        """
        根据 IP 获取地理位置
        
        Args:
            client_ip: 客户端 IP 地址
            
        Returns:
            包含城市/地区信息的字典，或 None
        """
        if not client_ip or client_ip in ['127.0.0.1', 'localhost', '::1', '::']:
            return None
        
        # 检查缓存
        if client_ip in self._cache:
            return self._cache[client_ip]
        
        try:
            # 使用 ip-api.com 免费 API (限制 45 请求/分钟)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"http://ip-api.com/json/{client_ip}",
                    params={"fields": "status,country,countryCode,region,regionName,city,zip"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        location = {
                            "country": data.get("country", ""),
                            "province": data.get("regionName", ""),  # 省/州
                            "city": data.get("city", ""),  # 城市
                            "coords": f"{data.get('city', '')},{data.get('regionName', '')}"  # 和风天气用
                        }
                        self._cache[client_ip] = location
                        return location
                        
        except Exception as e:
            print(f"[IP Location] 获取位置失败: {e}")
        
        return None
    
    def get_client_ip(self, request) -> str:
        """
        从请求中提取真实客户端 IP
        
        优先级:
        1. X-Forwarded-For (反向代理场景)
        2. X-Real-IP
        3. request.client.host
        """
        # X-Forwarded-For 格式: "client, proxy1, proxy2"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        if request.client:
            return request.client.host
        
        return ""
    
    def format_location_for_weather(self, location: dict) -> str:
        """
        将位置信息格式化为和风天气 API 需要的格式
        
        和风天气支持:
        - 城市名: "北京", "上海", "苏州"
        - 城市ID: CN101010100
        - 经纬度: "116.41,39.92"
        - IP: 使用 conn=ip 参数
        """
        if not location:
            return None
        
        city = location.get("city", "")
        province = location.get("province", "")
        
        # 优先使用城市名
        if city:
            # 去除"市"后缀（和风天气会自动识别）
            city = city.replace("市", "")
            return city
        
        if province:
            return province.replace("市", "")
        
        return None


# 全局实例
ip_location_service = IPLocationService()
