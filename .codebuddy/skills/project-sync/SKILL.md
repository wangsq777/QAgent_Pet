---
name: project-sync
version: 1.0.0
description: "QAgent Pet 项目 GitHub 同步工作流。当用户需要将项目更改同步到 GitHub 时触发，自动更新文档版本追踪并执行 git 推送。"
metadata:
  requires:
    bins: ["git", "python"]
---

# Project Sync - GitHub 同步工作流

当用户说"同步到 GitHub"、"推送代码"、"发布新版本"等意图时，按以下步骤执行工作流。

---

## Step 1: 检测变更并生成摘要

执行以下命令收集变更信息：

```bash
cd c:/Users/galbot/Desktop/QAgent_Pet
git status --short
git diff --stat
git diff HEAD
```

**AI 自动分析 `git diff` 输出，生成：**
1. **一行摘要**（简洁描述本次变更核心）
2. **变更要点列表**（3-5条要点，每条一句话）

将生成的摘要展示给用户审阅，格式如下：

```
📋 本次变更摘要（AI 自动生成）：

一行摘要：{AI 生成的一行总结}

变更要点：
- 要点1
- 要点2
- 要点3

是否确认？可以修改后再确认：
```

用户可以修改或直接确认。确认后进入下一步。

---

## Step 2: 确认版本号

读取当前版本信息：
- `main.py` 中的 `version` 字段
- 最新的 git tag（`git tag --sort=-v:refname | head -1`）

自动推导新版本号（SemVer 规则）：
- **Patch**（v1.0.0 → v1.0.1）：仅 bug 修复、文档更新
- **Minor**（v1.0.0 → v1.1.0）：新增功能但向后兼容
- **Major**（v1.0.0 → v2.0.0）：不兼容的重大变更

提示用户确认或修改版本号。

---

## Step 3: 更新 README.md - 版本追踪

使用 Python 脚本 `scripts/update_changelog.py` 在 `docs/README.md` 中追加版本追踪记录。

**操作指令：**
```bash
python scripts/update_changelog.py --readme docs/README.md --version "{新版本号}" --summary "{一行摘要}" --details "{要点1}；{要点2}；{要点3}"
```

该脚本会：
1. 检查 README.md 末尾是否已有 `## 版本追踪` 章节
2. 如果没有，在 `## 未来展望` 之前创建 `## 版本追踪` 章节
3. 如果有，在章节末尾追加新的版本条目

---

## Step 4: 更新需求实现文档

使用 Python 脚本追加修订记录：

```bash
python scripts/update_changelog.py --revision docs/QAgent_Pet_需求实现文档.md --version "{新版本号}" --content "{简短修订描述}"
```

然后**交互式引导用户**：
1. 根据本次 `git diff` 的变更，AI 判断哪些需求章节已被实现
2. AI 列出建议删除的章节/内容
3. 用户确认后，AI 将这些内容标记为已实现或删除
4. 对于需求实现文档中已实现完毕的功能，将对应章节标注 `~~已实现~~`

**常见操作示例：**
- 如果自定义宠物功能已实现，将第10章（可自定义宠物 Agent 需求）的开头添加标注
- 将需求实现文档中对应的需求任务从文档中移除或标注为已完成

---

## Step 5: 更新产品方案文档

将本次新增的功能补充到 `docs/QAgent_Pet_产品方案.md`：

1. 根据 `git diff` 分析，AI 识别新增功能
2. 引导用户将新功能描述补充到对应章节：
   - 新增功能 → 第3章"核心功能设计"
   - 宠物角色变更 → 第2章"宠物角色设计"
   - 后期规划的新增路线 → 第7章"后期规划"
3. 用户确认后直接修改文档

---

## Step 6: 可选 - 更新 main.py version

询问用户是否需要同步更新 `main.py` 中的 `version` 字段。

如果确认，修改 `main.py` 中的版本号。

---

## Step 7: Git 操作

按顺序执行：

```bash
# 1. 添加所有文档变更
git add docs/README.md docs/QAgent_Pet_需求实现文档.md docs/QAgent_Pet_产品方案.md
git add scripts/
git add .codebuddy/

# 如果有 main.py 变动
git add main.py

# 2. 提交
git commit -m "release: {新版本号} - {一行摘要}"

# 3. 推送
git push origin {当前分支}
```

如果 push 失败（如网络问题），保留本地 commit，提示用户手动处理。

---

## Step 8: 完成报告

工作流完成后，输出最终报告摘要：

```
✅ GitHub 同步完成！

版本：{新版本号}
分支：{当前分支}
提交信息：release: {新版本号} - {一行摘要}

已更新文档：
- docs/README.md（版本追踪已追加）
- docs/QAgent_Pet_需求实现文档.md（修订记录已更新）
- docs/QAgent_Pet_产品方案.md（功能描述已同步）

Git commit: {commit hash}
```

---

## 注意事项

1. **确保 git 配置正确**：操作前检查 `git config user.name` 和 `git config user.email`
2. **分支保护**：不直接操作 main/master 分支的 force push
3. **文件备份**：修改文档前展示 diff 预览，用户确认后再写入
4. **错误恢复**：任何步骤失败时，回滚已修改的文档文件
