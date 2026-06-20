"""
GitHub 公开仓库读取服务

仅支持 github.com/{owner}/{repo} 形式的公开仓库，不使用 Token、不 clone 仓库、不执行代码。
所有 HTTP 请求都经 httpx，限制只允许 host=api.github.com / raw.githubusercontent.com，
从源头规避 SSRF 风险。文件内容、目录树、README 均做字符数上限，控制 token 消耗。
"""

import base64
import re
from urllib.parse import unquote
from typing import Optional, Dict, List, Any
import httpx
from backend.logging_config import get_logger

logger = get_logger(__name__)

# 只允许这两个 GitHub 官方域名，避免 SSRF
ALLOWED_API_HOSTS = {"api.github.com", "raw.githubusercontent.com"}
GITHUB_URL_PATTERN = re.compile(
    r'^https?://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38}[A-Za-z0-9])?)/(?P<repo>[A-Za-z0-9._-]+)/?'
)

# 大小与数量上限
MAX_README_CHARS = 6000          # README 摘要最大字符数
MAX_TREE_ENTRIES = 300           # 目录树最多展示条目
MAX_TREE_DEPTH = 4               # 目录树最大深度
MAX_FILE_CHARS = 12000           # 单个文件最大字符数
MAX_CHAPTER_TOTAL_CHARS = 24000  # 单章 focus_paths 总字符数
MAX_FOCUS_FILES = 6              # 单章最多拉取文件数
HTTP_TIMEOUT = 20.0

# 关键文件名匹配（用于大纲前的项目概况）
KEY_FILE_NAMES = {
    "readme.md", "readme.txt", "readme", "package.json", "pom.xml",
    "build.gradle", "requirements.txt", "pyproject.toml", "go.mod",
    "cargo.toml", "composer.json", "gemfile", "dockerfile", "main.py",
    "main.js", "main.ts", "index.js", "index.ts", "app.py", "manage.py",
    "setup.py", "makefile", "cmakelists.txt", "tsconfig.json", "vite.config.js",
    "vite.config.ts", "next.config.js", "render.yaml", "vercel.json"
}


class GithubError(Exception):
    """对外暴露的可读错误，不带敏感细节"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def parse_github_url(url: str) -> Dict[str, str]:
    """
    解析并校验 GitHub 仓库 URL，仅允许 github.com/{owner}/{repo} 公开仓库。
    返回 {owner, repo, repo_full_name, github_url}。
    """
    if not url or not isinstance(url, str):
        raise GithubError("GitHub 仓库链接不能为空")
    url = url.strip()
    if len(url) > 500:
        raise GithubError("GitHub 仓库链接过长")
    # 先解码 URL 编码，避免 %2F / %2e 等绕过下方字符集白名单
    url = unquote(url)

    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise GithubError("仅支持 github.com/{owner}/{repo} 形式的公开仓库链接")

    owner = match.group("owner")
    repo = match.group("repo")
    # 拒绝带危险 path / query 试图跳转的链接（如 ..、@、注入）
    remainder = url[match.end():]
    if remainder and not remainder.startswith(("/", "?", "#", ".git")):
        # 允许 .git 结尾
        if not (url.endswith(".git") and remainder == ".git"):
            raise GithubError("仅支持仓库根链接，不支持子路径")

    # 去掉可能的 .git 后缀
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise GithubError("GitHub 仓库链接缺少 owner 或 repo")
    if ".." in owner or ".." in repo:
        raise GithubError("非法的 GitHub 仓库链接")

    normalized = f"https://github.com/{owner}/{repo}"
    return {
        "owner": owner,
        "repo": repo,
        "repo_full_name": f"{owner}/{repo}",
        "github_url": normalized,
    }


class GithubService:
    def __init__(self):
        # 不使用 Token：匿名调用 GitHub 公开 API，受官方匿名限流约束
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "QAgent-Pet-Learning",
        }

    async def _get(self, url: str, *, caller: str, accept_json: bool = True) -> Any:
        """统一 GET，限制只允许白名单 host。"""
        # 再次校验 host，杜绝 SSRF
        host = httpx.URL(url).host
        if host not in ALLOWED_API_HOSTS:
            raise GithubError("仅允许访问 GitHub 官方域名", status=400)

        headers = dict(self._headers)
        if not accept_json:
            headers["Accept"] = "text/plain; charset=utf-8"

        try:
            # SSRF 防护：禁止跟随重定向，否则 3xx 可绕过 host 白名单跳转到内网地址
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
                resp = await client.get(url, headers=headers)
        except httpx.RequestError as e:
            logger.warning("[github:%s] request error: %s", caller, e)
            raise GithubError("访问 GitHub 失败，请稍后重试", status=502)

        # 显式拒绝重定向：不跟随未经校验的跳转目标
        if resp.is_redirect or 300 <= resp.status_code < 400:
            logger.warning("[github:%s] unexpected redirect to: %s", caller, resp.headers.get("location", ""))
            raise GithubError("GitHub 返回了非预期的重定向，已拒绝", status=502)

        if resp.status_code == 404:
            raise GithubError("GitHub 仓库不存在或不可访问", status=404)
        if resp.status_code == 403:
            # 通常是匿名 rate limit
            raise GithubError("GitHub API 访问受限（可能触发匿名限流），请稍后再试", status=429)
        if resp.status_code >= 400:
            logger.warning("[github:%s] http %d: %s", caller, resp.status_code, resp.text[:200])
            raise GithubError(f"GitHub 请求失败（HTTP {resp.status_code}）", status=502)

        if accept_json:
            return resp.json()
        return resp.text

    async def get_repo_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """获取仓库基础信息：description、default_branch、language 等。"""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        data = await self._get(url, caller="repo_info")
        return {
            "owner": owner,
            "repo": repo,
            "repo_full_name": f"{owner}/{repo}",
            "description": data.get("description") or "",
            "default_branch": data.get("default_branch") or "main",
            "language": data.get("language") or "",
            "stargazers_count": data.get("stargazers_count", 0),
            "topics": data.get("topics") or [],
        }

    async def get_readme(self, owner: str, repo: str, default_branch: str) -> str:
        """获取 README 内容，限制最大字符数。缺失返回空串。"""
        # 优先用 raw.githubusercontent.com 拉取常见 README 文件名，避免 API 编码处理
        for name in ("README.md", "README.MD", "README", "readme.md", "Readme.md"):
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{name}"
            try:
                text = await self._get(url, caller="readme", accept_json=False)
            except GithubError as e:
                if e.status == 404:
                    continue
                raise
            if text:
                return text[:MAX_README_CHARS]
        return ""

    async def get_tree(self, owner: str, repo: str, default_branch: str) -> List[str]:
        """
        获取仓库目录树（递归），返回受数量与深度限制的文件路径列表。
        """
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
        )
        try:
            data = await self._get(url, caller="tree")
        except GithubError as e:
            if e.status == 404:
                return []
            raise

        tree = data.get("tree") or []
        paths: List[str] = []
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""
            if not path:
                continue
            # 跳过 node_modules / .git / dist 等噪音目录
            if any(seg in path.split("/") for seg in (
                "node_modules", ".git", "dist", "build", "vendor", "venv", ".venv"
            )):
                continue
            # 深度限制
            if len(path.split("/")) > MAX_TREE_DEPTH:
                continue
            paths.append(path)
            if len(paths) >= MAX_TREE_ENTRIES:
                break
        return paths

    def select_key_files(self, tree_paths: List[str]) -> List[str]:
        """从目录树中筛选关键文件（README、依赖、入口、配置等）。"""
        result = []
        seen = set()
        for path in tree_paths:
            base = path.rsplit("/", 1)[-1].lower()
            if base in KEY_FILE_NAMES and base not in seen:
                result.append(path)
                seen.add(base)
            if len(result) >= 12:
                break
        return result

    async def fetch_file(self, owner: str, repo: str, default_branch: str, path: str) -> Optional[str]:
        """拉取单个文件内容，限制最大字符数。失败/过大返回 None。"""
        if not path or len(path) > 300:
            return None
        # 拒绝绝对路径或路径穿越
        if path.startswith("/") or ".." in path.split("/"):
            return None
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"
        try:
            text = await self._get(url, caller="file", accept_json=False)
        except GithubError as e:
            if e.status in (404, 429):
                return None
            raise
        if not text:
            return None
        return text[:MAX_FILE_CHARS]

    async def fetch_chapter_files(
        self,
        owner: str,
        repo: str,
        default_branch: str,
        focus_paths: List[str]
    ) -> List[Dict[str, str]]:
        """
        按 focus_paths 拉取章节相关文件内容，单文件与单章总长度都受限。
        返回 [{"path": ..., "content": ...}, ...]。
        """
        files: List[Dict[str, str]] = []
        total_chars = 0
        for path in focus_paths[:MAX_FOCUS_FILES]:
            content = await self.fetch_file(owner, repo, default_branch, path)
            if not content:
                continue
            # 单章总长度上限
            if total_chars + len(content) > MAX_CHAPTER_TOTAL_CHARS:
                remaining = MAX_CHAPTER_TOTAL_CHARS - total_chars
                if remaining > 200:
                    content = content[:remaining] + "\n...(文件已截断)"
                    files.append({"path": path, "content": content})
                    total_chars += len(content)
                break
            files.append({"path": path, "content": content})
            total_chars += len(content)
        return files

    async def analyze_repo(self, github_url: str) -> Dict[str, Any]:
        """
        一次性聚合仓库分析所需信息：基础信息、README、目录树、关键文件。
        供大纲生成使用。任何环节缺失都尽量降级而非整体失败。
        """
        parsed = parse_github_url(github_url)
        owner = parsed["owner"]
        repo = parsed["repo"]

        info = await self.get_repo_info(owner, repo)
        default_branch = info["default_branch"]

        readme = ""
        try:
            readme = await self.get_readme(owner, repo, default_branch)
        except GithubError as e:
            logger.warning("获取 README 失败: %s", e.message)

        tree_paths: List[str] = []
        try:
            tree_paths = await self.get_tree(owner, repo, default_branch)
        except GithubError as e:
            logger.warning("获取目录树失败: %s", e.message)

        key_files = self.select_key_files(tree_paths)

        return {
            **info,
            "readme": readme,
            "tree_paths": tree_paths,
            "key_files": key_files,
            "tree_truncated": len(tree_paths) >= MAX_TREE_ENTRIES,
        }


github_service = GithubService()
