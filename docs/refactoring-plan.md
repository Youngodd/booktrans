# book-translator 重构计划

> 来源：对 `booktrans/` 的依赖图分析（`ast` 静态扫描）和 git 历史共同变更分析（73 个提交，其中 37 个改动 2–15 个文件的提交入样）。
> 样本较小，下列"共同变更"结论是线索，动手前请用实际代码确认。
> 撰写时代码库有未提交改动（`web/app.py`、`web/static/*` 等），行号和文件规模以重构开始时为准。

## 1. 概述

book-translator 把书籍（PDF/EPUB）翻译成目标语言并输出双语或单语 PDF，有命令行、Web、桌面（`desktop/`）三种入口，共用 `pipeline` 核心。整体分层清晰，基础层（`backends`、`languages`、`fsutil`）干净，多入口共用同一核心。
重构的目的不是推倒重来，而是消除三处会随功能增加而放大的问题：复制出来的中英文页面、入口层对 `pipeline` 参数的重复适配、层次放错位置造成的循环依赖。

## 2. 当前问题

| # | 问题 | 位置 | 影响 | 严重度 |
|---|---|---|---|---|
| P1 | 中英文页面是整份复制，每次必然同时修改（共同变更置信度 1.00） | `web/static/desktop.{en,zh}.html`（170/173 行）、`web.{en,zh}.html`（122/125 行）、`*.en.js` / `*.zh.js`（各 60 / 30 行左右字典） | 每加一个界面元素改两遍，容易漏改、漏翻；新增语言要再复制一份 | 高 |
| P2 | 入口层各自把用户选项转成 `pipeline` 参数，`pipeline` 一变入口都要改 | `cli.py:run()`（`translate_book` 调用在约 231/245/255 行）、`web/jobs.py:run_job()`（约 276 行）；`pipeline.py:translate_book` 有 14 个关键字参数 | `cli↔pipeline` 0.86、`jobs↔pipeline` 0.75、`cli↔jobs` 5 次同改。加一个选项要改 3 处以上 | 高 |
| P3 | `glossary ↔ translate` 循环依赖，靠延迟导入绕过 | `translate.py:6` 顶层导入 `glossary`；`glossary.py:164` 函数内 `from .translate import complete`（注释自己写明原因）；`complete` 定义在 `translate.py:15` | 目前运行无误，历史上也没有造成同改；但说明 `complete` 位置放错了层，之后加依赖易出事 | 中 |
| P4 | 桌面壳与 Web 应用绑得紧 | `desktop/shell.py`（313 行）↔ `web/app.py`（592 行）同改 6 次，置信度 0.86；`tests/test_desktop.py` 随 `app.py` 同改 8 次 | 壳不稳定，说明其接口或职责边界不清 | 中 |
| P5 | `web/app.py` 与 `web/jobs.py` 总是一起改，且 `app.py` 扇出 12（最高） | `web/app.py`、`web/jobs.py`（308 行） | 每个功能要同时动两个文件，`app.py` 有变成上帝模块的趋势 | 中 |
| P6 | 共用代码放在入口模块里 | `desktop/shell.py:80,136` 从 `desktop/__main__.py` 导入 `data_dir`；`desktop/__main__.py` 又依赖 `web.app` | 入口模块被别的模块导入，不是好习惯，也增加循环风险 | 低 |

## 3. 重构建议

### R1 中英文页面合并为模板 + 语言字典（解决 P1）
- **改动**：每个页面（desktop、web）只保留一份 HTML，文案抽到语言字典。项目已有 `desktop.en.js` 的 `T = {...}` 形式字典，沿用该做法，按 `lang` 加载对应字典并渲染。
- **涉及文件**：`web/static/desktop.{en,zh}.html`、`desktop.js`、`desktop.{en,zh}.js`、`web.{en,zh}.html`、`web.js`、`web.{en,zh}.js`、`langs.js`，以及 `web/app.py` 中提供这些页面的路由。
- **收益**：改一处即可；新增语言只要加一个字典；两种语言不会再有结构漂移。

### R2 为 `pipeline` 引入统一配置对象（解决 P2）
- **改动**：新增 `JobOptions`（dataclass 一类），把 `translate_book` 的 14 个关键字参数收拢进去。`cli` 和 `jobs` 只负责把各自的输入（命令行参数 / 表单）填进 `JobOptions`，再调用 `pipeline`。
- **涉及文件**：`pipeline.py`、`cli.py`、`web/jobs.py`，可能涉及 `web/app.py`。
- **收益**：加选项只改 `JobOptions` 和 `pipeline`；两个入口不再各自重复默认值和校验。

### R3 把 `complete` 移出 `translate`（解决 P3）
- **改动**：将 `complete(backend, system, text, max_tokens)` 移到 `backends` 层（例如 `backends/base.py` 的辅助函数，或新建 `llm.py`），`translate` 和 `glossary` 都从那里导入，去掉 `glossary.py:164` 的延迟导入。
- **涉及文件**：`translate.py`、`glossary.py`、`ocr.py`（它也导入 `translate`，需确认是否同样用到 `complete`）。
- **收益**：消除循环；依赖方向恢复单向。

### R4 明确桌面壳和 Web 应用的接口（解决 P4、P6）
- **改动**：先阅读 `shell.py` 与 `app.py` 的交互点，列出壳实际调用的内容；把应用的启动、端口、数据目录等整理成一个小而稳定的入口（如 `create_app(...)`），壳只依赖它。把 `data_dir` 从 `desktop/__main__.py` 移到 `desktop/` 下的普通模块。
- **涉及文件**：`desktop/shell.py`、`desktop/__main__.py`、`web/app.py`，以及 `tests/test_desktop.py`。
- **收益**：壳的改动不再牵动应用；桌面测试不必随 `app.py` 内部变化而改。

### R5 检查 `app.py` / `jobs.py` 的职责划分（解决 P5）
- **改动**：约定 `app.py` 只管路由和请求校验，`jobs.py` 只管任务调度与状态。把落在错误一侧的逻辑挪过去；若 R2 已完成，此项的工作量会明显减小。
- **涉及文件**：`web/app.py`、`web/jobs.py`。
- **收益**：每个功能不必再同时改两个文件；`app.py` 的规模受控。

## 4. 分阶段计划

依赖关系：R3 独立；R2 先于 R5；R4 最好在 R2 之后；R1 独立，可并行。

| 阶段 | 事项 | 理由 | 完成标准（done when） |
|---|---|---|---|
| 0 | 记录基线 | 重构前先确认现状可验证 | `pytest` 全绿；依赖图脚本输出已保存；工作区未提交改动已提交或暂存，不混入重构 |
| 1 | R3：移动 `complete` | 改动小、风险低、立刻消除环 | 依赖图中无环；`glossary.py` 没有函数内 `from .translate import ...`；测试全绿 |
| 2 | R1：页面合并 | 收益最大，且独立于 Python 逻辑 | 每个页面只有一份 HTML；中英文切换行为与现在一致；新增一个占位语言只需添加一个字典文件 |
| 3 | R2：`JobOptions` | 为 R4、R5 铺路 | `cli.py` 和 `jobs.py` 不再各自列出 `translate_book` 的所有参数；增加一个选项时只需改 `JobOptions` 和 `pipeline` |
| 4 | R4：桌面壳接口 | 依赖稳定下来的应用入口 | `shell.py` 只通过一个明确入口使用 `web.app`；`data_dir` 不再从 `__main__` 导入；`test_desktop.py` 不依赖 `app.py` 内部细节 |
| 5 | R5：`app.py`/`jobs.py` 职责 | 最后整理，视前面成果决定做多少 | 约定写进文件头注释或 ADR；随意选一个典型新功能，改动不再同时需要两边的业务逻辑 |

每个阶段单独提交，保证随时可回退。

## 5. 风险与验证

| 风险 | 验证方式 |
|---|---|
| 页面合并后文案缺失、中英文显示错乱 | 阶段 2 前对两个页面的两种语言各截一次图作基线；合并后逐项对照；检查字典 key 是否两边都齐全 |
| 参数收拢后默认值悄悄变化 | 先给 `cli` 和 `jobs` 调用 `translate_book` 的路径补测试（断言传入参数），再动手；对比重构前后同一输入的缓存键和输出 |
| 移动 `complete` 后别处还在从 `translate` 导入 | `grep -rn "translate import"`；跑 `tests/`；重跑依赖图脚本确认无环 |
| 桌面壳改动在 Windows 上才暴露问题 | 项目已有 `docs/WINDOWS_VM_TEST_PLAN.md`、`docs/MANUAL_TEST.md`，阶段 4 后按其流程至少过一遍 |
| 已有的未提交改动被重构混淆 | 阶段 0 先处理掉 |

可补充的自动检查（阶段 1 之后）：用 import-linter 或自写测试禁止新增循环依赖，并规定"基础层不得导入 `pipeline` 以上"（工具选择需自行确认当前状态，verify before adopting）。

## 6. 暂不纳入

- JS 页面、`miniprogram/` 的依赖分析：本次只扫描了 Python 的模块级导入，没有覆盖。
- 函数级调用图：没有做，需要时再用 LSP 或 tree-sitter 补充。
- 引入新框架或大规模目录重组：现有分层已经够用，不在本次范围。
- 基于代码图谱的 AI 上下文工具：和此次重构无关，留待以后。

## 附：重新生成依赖图和共同变更统计

依赖图已保存为 [dependency-graph.md](dependency-graph.md)。

- 依赖图脚本：`/private/tmp/claude-501/-Users-yangchuan-Developer-book-translator/035b9780-4e40-4bfd-96a3-3104f1f08fb1/scratchpad/depgraph.py`（输出 Mermaid，环和扇入/扇出打印到 stderr）
- 共同变更脚本：`/private/tmp/claude-501/-Users-yangchuan-Developer-book-translator/035b9780-4e40-4bfd-96a3-3104f1f08fb1/scratchpad/cochange.py`

这两个脚本在临时目录里，重启后可能被清理。需要长期使用的话，建议复制到项目的 `tools/` 下。
