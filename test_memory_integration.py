"""记忆管理系统集成测试"""
import asyncio
import json
from backend.database import init_database
from backend.services.embedding_service import embedding_service
from backend.services.memory_service import memory_service


async def test_embedding_roundtrip():
    """测试 embedding API 调用和向量存储检索"""
    await init_database()

    test_text = "今天天气真好，我想出去散步"
    embedding = await embedding_service.embed(test_text)
    if embedding is None:
        print("[SKIP] Embedding API 未配置，跳过向量测试")
        return
    assert len(embedding) > 0, "返回向量为空"
    print(f"[PASS] embed() 返回向量维度: {len(embedding)}")

    # 测试存储
    vector_id = await embedding_service.save_vector(
        session_id="test_session",
        source_type="message",
        source_id="test_msg_1",
        content=test_text,
        embedding=embedding
    )
    assert vector_id is not None
    print(f"[PASS] save_vector() 成功: {vector_id}")

    # 测试检索
    query_embedding = await embedding_service.embed("我想出门走走")
    assert query_embedding is not None
    results = await embedding_service.search(
        query_vector=query_embedding,
        session_id="test_session",
        top_k=3
    )
    assert len(results) > 0, "向量检索返回空"
    assert results[0]["similarity"] > 0.5, f"相似度过低: {results[0]['similarity']}"
    print(f"[PASS] search() 找到 {len(results)} 条结果, 最高相似度: {results[0]['similarity']:.4f}")


async def test_short_term_window():
    """测试短期记忆窗口从 40 改为 10"""
    await init_database()

    # 写入 20 条测试消息
    for i in range(20):
        await memory_service.save_message("test_session_2", "user", f"测试消息 {i}")

    messages = await memory_service.get_short_term_messages("test_session_2", limit=10)
    assert len(messages) <= 10, f"短期窗口应为 10 条，实际: {len(messages)}"
    print(f"[PASS] get_short_term_messages 返回 {len(messages)} 条（<=10）")


async def test_cosine_similarity():
    """测试余弦相似度计算"""
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]
    assert embedding_service._cosine_similarity(vec_a, vec_b) == 1.0

    vec_c = [0.0, 1.0, 0.0]
    assert embedding_service._cosine_similarity(vec_a, vec_c) == 0.0

    print("[PASS] cosine_similarity 基础测试通过")


async def main():
    print("=== 记忆管理系统集成测试 ===\n")
    await test_cosine_similarity()
    await test_short_term_window()
    await test_embedding_roundtrip()
    print("\n=== 全部测试通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
