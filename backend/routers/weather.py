"""天气穿衣建议（「帮你选」）：次日预报 + 当前宠物人格化建议。"""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.database import get_db
from backend.schemas import WeatherOutfitRequest
from backend.services.llm_service import llm_service
from backend.services.proactive_service import load_pet_persona
from backend.services.weather_service import build_outfit_advice, weather_service
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/weather", tags=["weather"])
limiter = Limiter(key_func=get_remote_address)

_NO_CITY_HINT = "先告诉我你在哪个城市吧，可以在记忆档案里补充地区"


@router.post("/outfit-advice")
@limiter.limit("10/minute")
async def outfit_advice(body: WeatherOutfitRequest, request: Request):
    """返回次日天气与穿衣建议。city 缺省时读用户画像 region，绝不编造城市。"""
    user_id = request.state.user_id
    city = (body.city or "").strip()
    if not city:
        async with get_db() as db:
            cursor = await db.execute("SELECT region FROM user_profiles WHERE user_id=?", (user_id,))
            row = await cursor.fetchone()
        city = (row[0] or "").strip() if row else ""
    if not city:
        raise HTTPException(status_code=400, detail=_NO_CITY_HINT)

    forecast = await weather_service.get_daily_forecast(city)
    if not forecast:
        raise HTTPException(status_code=404, detail=f"查不到「{city}」的天气信息，换个城市名试试")
    tomorrow = forecast["tomorrow"]

    advice = ""
    persona = None
    async with get_db() as db:
        persona = await load_pet_persona(db, user_id)
    if persona and persona.get("system_prompt"):
        weather_line = (
            f"城市：{forecast['city']}；明天（{tomorrow['date']}）：{tomorrow['text']}，"
            f"最高{tomorrow['temp_max']}°C，最低{tomorrow['temp_min']}°C，"
            f"降水概率{tomorrow['precip_probability']}%，降水量{tomorrow['precip_sum']}mm"
        )
        prompt = (
            f"{weather_line}\n请根据明天的天气，用 1-2 句话给主人实用的穿衣建议，"
            "要符合你的性格和口头禅，直接输出建议内容，不要任何解释。"
        )
        try:
            text = await asyncio.wait_for(
                llm_service.chat(
                    [{"role": "system", "content": persona["system_prompt"]},
                     {"role": "user", "content": prompt}],
                    temperature=0.8, max_tokens=400, caller="weather_outfit", timeout=10.0,
                ),
                timeout=15.0,
            )
            text = (text or "").strip()
            if text and len(text) <= 200:
                advice = text
        except Exception as exc:
            logger.warning("weather_outfit LLM failed, fallback to template: %s", exc)
    if not advice:
        advice = build_outfit_advice(tomorrow)

    return {
        "city": forecast["city"],
        "date": tomorrow["date"],
        "weather": {
            "text": tomorrow["text"],
            "temp_max": tomorrow["temp_max"],
            "temp_min": tomorrow["temp_min"],
            "precip_probability": tomorrow["precip_probability"],
            "precip_sum": tomorrow["precip_sum"],
        },
        "advice": advice,
    }
