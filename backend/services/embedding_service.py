import json
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx
import numpy as np

from backend.config import settings
from backend.database import get_db


class EmbeddingService:
    def __init__(self):
        self.api_url = settings.EMBEDDING_API_URL or f"{settings.LLM_BASE_URL}/embeddings"
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self.model = settings.EMBEDDING_MODEL

    async def embed(self, text: str) -> Optional[List[float]]:
        """调用云端 Embedding API 获取文本向量"""
        if not self.api_key or not text or not text.strip():
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": text.strip()[:2000]
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                embedding = data["data"][0]["embedding"]
                return embedding
        except Exception as e:
            print(f"[EmbeddingService] embed failed: {e}")
            return None

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        a = np.array(vec_a)
        b = np.array(vec_b)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    async def save_vector(
        self,
        session_id: str,
        source_type: str,
        source_id: str,
        content: str,
        embedding: List[float],
        importance: float = 0.5
    ) -> str:
        """保存向量到数据库"""
        vector_id = str(uuid.uuid4())
        embedding_json = json.dumps(embedding)

        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO memory_vectors (vector_id, session_id, source_type, source_id, content, embedding, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vector_id, session_id, source_type, source_id, content, embedding_json, importance, datetime.now())
            )
            await db.commit()
        return vector_id

    async def search(
        self,
        query_vector: List[float],
        session_id: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
        exclude_source_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """向量相似度检索"""
        exclude_set = set(exclude_source_ids or [])

        async with get_db() as db:
            if source_type:
                cursor = await db.execute(
                    "SELECT vector_id, source_type, source_id, content, embedding, importance, created_at FROM memory_vectors WHERE session_id = ? AND source_type = ?",
                    (session_id, source_type)
                )
            else:
                cursor = await db.execute(
                    "SELECT vector_id, source_type, source_id, content, embedding, importance, created_at FROM memory_vectors WHERE session_id = ?",
                    (session_id,)
                )
            rows = await cursor.fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            row_dict = dict(row)
            source_id = row_dict["source_id"]
            if source_id in exclude_set:
                continue

            stored_vector = json.loads(row_dict["embedding"])
            similarity = self._cosine_similarity(query_vector, stored_vector)

            created_at = datetime.fromisoformat(row_dict["created_at"])
            days_ago = (datetime.now() - created_at).days
            time_decay = max(0.5, 1.0 - max(0, days_ago - 7) * 0.05)

            score = similarity * time_decay * row_dict["importance"]

            results.append({
                "vector_id": row_dict["vector_id"],
                "source_type": row_dict["source_type"],
                "source_id": source_id,
                "content": row_dict["content"],
                "similarity": similarity,
                "score": score,
                "created_at": row_dict["created_at"]
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


embedding_service = EmbeddingService()
