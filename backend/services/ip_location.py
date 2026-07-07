"""
IP地理位置服务 - 自动获取用户所在地区
"""
import ipaddress
import httpx
from typing import Optional
import os
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)


def _parse_trusted_proxies(raw: str) -> set:
    """解析配置中的可信代理 CIDR / IP 集合"""
    trusted = set()
    if not raw:
        return trusted
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            # 同时支持单 IP 和 CIDR
            if "/" in part:
                trusted.add(ipaddress.ip_network(part, strict=False))
            else:
                trusted.add(ipaddress.ip_network(part + "/32", strict=False))
        except ValueError:
            logger.warning("忽略无效的可信代理配置项: %s", part)
    return trusted


class IPLocationService:
    """
    通过 IP 地址获取用户地理位置
    支持多种数据源：
    1. 免费 API: ip-api.com (推荐，无需 API Key)
    2. 反向代理场景下的 X-Forwarded-For / X-Real-IP（需配合可信代理配置）
    """

    def __init__(self):
        self._cache: dict = {}
        self._cache_ttl = 3600  # 缓存1小时
        self._trusted_proxies = _parse_trusted_proxies(getattr(settings, "TRUSTED_PROXIES", ""))

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
            # 优先走 HTTPS，避免明文传输客户端 IP（中间人可窃听/篡改）。
            # 注意：ip-api.com 免费版仅支持 HTTP，HTTPS 会返回 403；
            # 这里优先尝试 HTTPS，失败则回退 HTTP 并输出警告，便于生产切换到支持 HTTPS 的服务。
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"https://ip-api.com/json/{client_ip}",
                    params={"fields": "status,country,countryCode,region,regionName,city,zip"}
                )
                if response.status_code == 403:
                    logger.warning(
                        "ip-api.com HTTPS 不可用（免费版限制），回退到明文 HTTP。"
                        "生产环境请切换到支持 HTTPS 的 IP 定位服务。"
                    )
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
            logger.warning("获取位置失败: %s", e)

        return None

    def get_client_ip(self, request) -> str:
        """
        从请求中提取真实客户端 IP

        优先级:
        1. X-Forwarded-For（仅当直连来源是可信代理时才信任，防止客户端伪造）
        2. X-Real-IP（同上可信代理校验）
        3. request.client.host

        安全说明：
        - X-Forwarded-For / X-Real-IP 可被任意客户端伪造。
        - 仅当 request.client.host 落在配置的 TRUSTED_PROXIES 内时，才采纳这些头部。
        - 未配置 TRUSTED_PROXIES 时（本地开发），退化为直接信任连接 IP，
          并输出一次警告，提示生产必须配置可信代理。
        """
        peer = request.client.host if request.client else None

        def _is_trusted(ip_str: str) -> bool:
            if not ip_str:
                return False
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                return False
            return any(addr in net for net in self._trusted_proxies)

        # 未配置可信代理：仅本地开发可接受，生产必须配置
        if not self._trusted_proxies:
            # 本地开发：保留旧行为以不破坏现有流程，但限制为回环地址
            if peer in ("127.0.0.1", "::1", "localhost"):
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    return forwarded.split(",")[0].strip()
                real_ip = request.headers.get("x-real-ip")
                if real_ip:
                    return real_ip.strip()
            return peer or ""

        # 配置了可信代理：仅信任来自代理的转发头
        if _is_trusted(peer):
            # X-Forwarded-For 格式: "client, proxy1, proxy2"，取最左客户端
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip.strip()

        return peer or ""
    
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
