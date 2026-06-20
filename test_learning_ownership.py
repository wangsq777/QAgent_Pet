"""跨用户归属校验测试：用户 B 不得读取/操作用户 A 的学习会话。"""
import json
import requests

BASE = "http://127.0.0.1:8766"
USER_A = "own_test_user_A_001"
USER_B = "own_test_user_B_001"


def main():
    pet_id = "hot_dog"
    github_url = "https://github.com/pallets/flask"

    # 用户 A 创建一个最小的学习会话（自定义大纲，避免依赖 LLM）
    headers_a = {"X-User-Id": USER_A, "Content-Type": "application/json"}
    outline = [{
        "chapter_id": 1, "title": "概览",
        "learning_goal": "了解项目", "focus_paths": ["README.md"]
    }]
    r = requests.post(f"{BASE}/api/learning/sessions", headers=headers_a,
                      json={"pet_id": pet_id, "github_url": github_url, "outline": outline}, timeout=30)
    assert r.status_code == 200, r.text
    session_id = r.json()["learning_session_id"]
    print("A created session:", session_id)

    headers_b = {"X-User-Id": USER_B, "Content-Type": "application/json"}

    # 1) 用户 B 读取会话详情 -> 403
    r = requests.get(f"{BASE}/api/learning/sessions/{session_id}", headers=headers_b, timeout=30)
    print("B GET detail ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 2) 用户 B teach -> 403
    r = requests.post(f"{BASE}/api/learning/sessions/{session_id}/chapters/1/teach",
                      headers=headers_b, timeout=30)
    print("B teach ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 3) 用户 B ask -> 403
    r = requests.post(f"{BASE}/api/learning/sessions/{session_id}/ask",
                      headers=headers_b,
                      json={"target": "teacher", "question": "x", "chapter_id": 1}, timeout=30)
    print("B ask ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 4) 用户 B complete_chapter -> 403
    r = requests.post(f"{BASE}/api/learning/sessions/{session_id}/chapters/1/complete",
                      headers=headers_b, timeout=30)
    print("B complete_chapter ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 5) 用户 B pause -> 403
    r = requests.post(f"{BASE}/api/learning/sessions/{session_id}/pause", headers=headers_b, timeout=30)
    print("B pause ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 6) 用户 B complete_session -> 403
    r = requests.post(f"{BASE}/api/learning/sessions/{session_id}/complete", headers=headers_b, timeout=30)
    print("B complete_session ->", r.status_code)
    assert r.status_code == 403, f"expected 403 got {r.status_code}"

    # 7) 用户 A 自己能读 -> 200
    r = requests.get(f"{BASE}/api/learning/sessions/{session_id}", headers=headers_a, timeout=30)
    print("A GET detail ->", r.status_code)
    assert r.status_code == 200, f"owner should read own session, got {r.status_code}"

    # 8) 伪造的 session_id 格式 -> 400
    r = requests.get(f"{BASE}/api/learning/sessions/not-a-uuid", headers=headers_a, timeout=30)
    print("bad uuid ->", r.status_code)
    assert r.status_code == 400

    print("\nOWNERSHIP_TESTS_PASSED")


if __name__ == "__main__":
    main()
