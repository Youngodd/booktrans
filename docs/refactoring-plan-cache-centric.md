# 以缓存为中心的重构计划：任意输入 → 缓存 → 任意输出

> 状态：草案，未改任何代码。撰写于 2026-11-14，基于 `booktrans/` 在提交 `d9d34de` 时的代码。
> 与 [refactoring-plan.md](refactoring-plan.md)（R1–R5）是两份独立的计划，重叠处见第 8 节。
> 文中凡写"`文件:函数`"的都是本次读过的代码；未读过或未验证的我会直接标出。

## 1. 目标

1. 每种输入（PDF、EPUB、Word `.docx`、Markdown）只解析一次，解析结果（按阅读顺序排列的内容块，含图和表）连同原文、译文一起存进缓存。
2. 每种输出（PDF、EPUB、`.docx`、Markdown）只从缓存生成，不再回到原文件去重新解析文本，也不再调用翻译后端。
3. 同格式输出尽量复刻原版式：PDF→双语 PDF 复制原页面布局，EPUB→双语 EPUB 保留原结构和样式。
4. 跨格式输出不要求像原格式：按原顺序输出全部内容，图和表也要有，版式用目标格式自己的合理样式。
5. 4×4 = 16 种输入输出组合走同一条路径，不写 16 个转换器。

## 2. 现状（读过的代码）

| 事实 | 出处 |
|---|---|
| 缓存是 `<state>.cache.json`，一个 JSON 字典：键 = `[目标语言:]["L"]页号`（`"L"` 表示版式页），值 = 整页译文字符串，或版式页的译文列表 | `translate.py:cache_key`、`translate_all` |
| **缓存里没有原文。** 每次运行都重新 `read_book`，再按位置对齐；版式页只靠 `len(cache[key]) != len(blocks)` 判断是否还对得上 | `pipeline.py:translate_book`、`translate.py:translate_all` |
| 缓存里没有版式（bbox、字号）、没有图、没有表。版式块每次由 `collect_layout` → `extract_blocks` / `extract_paragraphs` 重新抽取 | `layout.py:collect_layout`、`page_blocks` |
| 扫描页的 OCR 文字单独存在 `<state>.ocr.json`；词表使用记录在 `<state>.glossary-used.json` | `ocr.py:ocr_scanned_pages`、`pipeline.py:used_path` |
| EPUB 只取 `h1/h2/h3/p` 的文字，图、表、列表、样式全丢；再按约 1800 字切成"页"。TXT 同样切页 | `readers.py:read_epub`、`paginate`、`CHARS_PER_PAGE` |
| 输出只有 PDF：`make_pdf`（原页 + 译页交替，或只有译页）；文本页用 pymupdf `Story` 排版 | `writer.py:make_pdf`、`text_pages` |
| 输入只认 `.pdf/.epub/.txt`；输出文件名写死 `.pdf`（Web 里直接用 `output.pdf` 当 state 名） | `readers.py:read_book`、`pipeline.py:default_output`、`web/app.py:EXTENSIONS`、`web/jobs.py:run_job` |
| 已有的可复用资产：块抽取（PDF）、表格按单元格抽取、扫描页墨迹层、`KEEP="~"`（译者回答"保留原样"）、`JobOptions`、`complete` 已移到 `backends.base` | `layout.py`、`figures.py:ink_layer`、`options.py`、`translate.py:3` |

**与你的设想的差距：** "原文和译文都存在缓存里"目前不成立——只有译文在缓存里。所以本计划的核心是新增一份"文档缓存"（原文 + 结构 + 资源），而不是给现有缓存加字段。
另外，今天 EPUB 只能输出 PDF；"EPUB→EPUB"是新功能，不是要保住的旧功能。EPUB→PDF 要继续可用。

## 3. 目标架构

```
reader(pdf|epub|docx|md|txt) ──► Document（内容块序列 + 资源）──► <state>.book.json + <state>.assets/
                                         │
          translate_units(Document) ──► <state>.tr.<target>.json（按块 id 存译文）
                                         │
writer(pdf|epub|docx|md) ◄── Document + 译文 (+ 同格式时的原文件)
```

### 3.1 数据模型（新增 `booktrans/model.py`）

```python
Block:  id        "p12-3" 形式：来源位置 + 序号，稳定
        type      heading | paragraph | list_item | table | figure | caption | formula | code | footnote
        text      原文（table 无此字段，见 cells）
        level     heading 级别 / list 层级（可选）
        cells     table：[{r, c, rs, cs, text}]，单元格各自翻译
        asset     figure/formula：<state>.assets/ 下的文件名（内容哈希命名，去重）
        src       来源定位，按格式不同：
                  pdf  {page, bbox, size, bold, color, rects}   ← 现有块字段，原样保存
                  epub {item, idx}  （第 idx 个可翻译元素，用于同格式回写）
                  docx {para} / md {line}
        unit      翻译单元号（见 3.3）
        h         原文内容哈希，用来判断译文是否过期
Document: schema(=1), source{format, name, sha256, pages}, lang, blocks[]
Translations: {block_id: {text, h, glossary}}   # 每个目标语言一个文件
```

选择理由：
- **原文与译文分文件存。** 原文与目标语言无关，换目标语言不必重新解析；译文按目标语言分文件，延续现在"每个目标语言各有自己的键"的做法（`cache_key`）。读出来时合并成"每块有原文有译文"，满足你的设想。
- **按块 id + 哈希对齐，取代"按位置 + 长度"对齐。** 现在版式页用 `len(cache[key]) != len(blocks)` 判断，抽取算法一改就悄悄错位；哈希不符则只重译那一块。
- **图和表是一等公民。** 图存为资源文件，块里只有引用；表保留行列结构，所以能变成 Word 表、Markdown 表、HTML 表。
- **`src` 保留来源位置**，同格式输出（PDF 重画原页、EPUB 回写原 XHTML）靠它；跨格式输出不看它。
- 文件带 `schema` 版本号；版本不符就整体作废重建，不做半兼容。

### 3.2 读取器（输入）

接口：`read(path, options, progress) -> Document`。读取器不翻译、不渲染、不调用后端（OCR 例外，见风险 R-1，它在读取阶段、写入 `blocks`）。

| 输入 | 库 | 做法 | 已知限制 |
|---|---|---|---|
| PDF | pymupdf（已有） | 沿用 `extract_blocks`/`extract_paragraphs`；新增：标题判断（字号排名）、图（内嵌图片 `extract_image`；矢量图用 `get_pixmap(clip=…)` 截取）、表（沿用扫描页的表格识别，文本 PDF 用 `page.find_tables()`，**需读代码确认版本支持**） | 多栏顺序、公式、脚注靠启发式；见第 7 节 |
| EPUB | ebooklib + bs4（已有） | 按 spine 顺序走 DOM：`h1-6/p/li/table/img/figcaption/pre`；记 `src.item/idx` | 行内格式（链接、斜体）在纯文本块里丢失；MathML、嵌套表只能降级 |
| `.docx` | **python-docx（新依赖，待你决定）** | 段落样式名 → 标题/列表；表 → `table`；行内图 → 资源 | 文本框、脚注、批注、修订、艺术字读不到；不支持旧 `.doc` |
| Markdown | **markdown-it-py（新依赖，待你决定）** | token 流（带行号）→ 块；图片相对路径读入资源；行内标记原样留在 `text`，提示词要求保留 | 内嵌 HTML、脚注语法、远程图片（只记 URL，不下载） |
| TXT | 已有 `decode_text` | 空行分段，不再按 1800 字切页 | — |

库的许可（需核对）：python-docx、markdown-it-py 我记得都是 MIT，与 AGPL-3.0 兼容；这是凭记忆，**引入前要按 ADR 0003 的流程跑 `packaging/third_party.py` 并更新 `docs/THIRD_PARTY.md`**。现有 `requirements.txt` 里没有这两个库。

### 3.3 翻译单元

保持现在的做法：一个请求翻一批带编号的块，并带前后文（`translate_blocks`、`collect_layout` 里的 `ctx`）。
单元的划分变成块的字段 `unit`：PDF = 一页；其他格式 = 相邻块累计到约 1800 字（代替 `paginate`），但不在表格或列表中间切开。
`translate.py` 改为 `translate_units(backend, doc, tr, …)`：只翻哈希不符或缺失的块，每翻一个单元就落盘一次（保持现在"中断可续"）。`glossary-used` 记在译文条目的 `glossary` 字段里，不再另存一个文件。
图块和 `formula` 块不送翻译；译者返回 `KEEP`（`~`）的块，输出时保留原文。

### 3.4 写入器（输出）

接口：`write(doc, tr, out, mode, *, source_path=None, options)`。`mode` 是 `bilingual` 或 `target-only`。写入器只读 `Document` 和 `Translations`；同格式还可以读原文件（`source_path`）。

| 输出 | 同格式（尽量复刻） | 跨格式（按顺序输出） | 库 / 限制 |
|---|---|---|---|
| PDF | PDF→PDF：沿用 `render_layout_page`/`render_clean_page`，原页 + 译页交替；块的 bbox 来自缓存，但**仍需要原 PDF 文件**画底图 | 译文页用现有 `text_pages`（`Story` 排版）；图按 `asset` 插入，表画成 HTML 表 | pymupdf（已有）。需要确认 `Story` 对表格、图片的支持程度 |
| EPUB | EPUB→EPUB：复制原 zip，按 `src.item/idx` 在每个原元素后插入译文元素（双语）或替换（仅译文）；图、CSS、目录原样保留 | 用 ebooklib 新建：标题→`h*`，表→`table`，图→资源 | ebooklib（已有，AGPL）。目标语言为 RTL/CJK 时设 `dir`、`lang` |
| `.docx` | 第一版不做同格式回写，走跨格式（见"待定事项"） | 标题样式、列表、表格、图片；双语 = 原文段后紧跟译文段（译文换色） | python-docx；CJK 要同时设东亚字体，RTL 要设 `w:bidi` |
| Markdown | 同跨格式：结构本来就是线性的 | 标题 `#`、管道表、`![](<out>_assets/…)`；图片放在输出文件旁的目录里 | 手写序列化器，不用库 |

双语的统一规则（非 PDF 版式复刻时）：块按原顺序，每块"原文 + 译文"相邻；图只出现一次，图注两种语言都出；表格单元格内原文换行后接译文。

### 3.5 `pipeline.py` 变成什么样

```python
def translate_book(book, out, translator, options=None, *, ocr_backend=None, progress=None, meter=None):
    doc = store.load_or_read(book, state, options, ocr_backend, progress)   # 读一次，存缓存
    tr  = store.load_translations(state, options.target)
    translate_units(translator, doc, tr, ..., glossary, progress)           # 只补缺的
    writers.for_path(out).write(doc, tr, out, options.output_mode, source_path=book)
```

`pipeline.py` 里 `glossary_changes`、`draft_glossary`、`detect_book_language`、`total_pages` 等今天各自调用 `read_book` 的函数，改为读 `Document`（`read_book` 返回页文字列表的做法随之取消）。`only_cached` 变成"按现有译文写出，缺的单元用原文占位或省略"，不再需要特殊分支。

### 3.6 模块布局

```
booktrans/model.py            Block / Document / Translations（只依赖标准库）
booktrans/store.py            读写 book.json、tr.<target>.json、assets/；旧缓存迁移
booktrans/readers/{__init__,pdf,epub,docx,md,txt}.py     （readers.py 变成包）
booktrans/writers/{__init__,pdf,epub,docx,md}.py         （writer.py 变成包）
booktrans/translate.py        translate_units（保留 translate / translate_blocks）
booktrans/pipeline.py         read → translate → write
```
`layout.py` 的抽取函数迁到 `readers/pdf.py`，渲染函数迁到 `writers/pdf.py`；`figures.py` 随渲染走。
`tests/test_architecture.py` 要加两条：读取器和写入器互不导入，二者都只依赖 `model`；`model` 不导入任何 booktrans 模块。

## 4. 旧缓存怎么办

旧文件不删、不改，所以随时可以回退。第一次打开旧书时：
- **PDF 版式页（`L<页号>` 键）：** 新读取器用同一套抽取算法得到块，若块数与旧列表长度相等就逐块对上，免费迁移；不相等则该页作废重译。
- **整页字符串（扁平 PDF、OCR 页、EPUB/TXT）：** 新块的切法和旧"页"不同，原则上对不上。能按空行段数对上的迁移，对不上的作废。**这意味着部分旧书会重新付费**，见待定事项 1。
- 迁移在 `store.py` 里，写一个函数、带测试；用仓库根目录里已有的真实缓存（`ChemicalTree_*.cache.json`、`Research_bilingual.cache.json`）做手工验证，不把它们提交进测试。

## 5. 分阶段步骤

每一步单独提交，并且每一步结束时 PDF→PDF 和 EPUB→PDF 都能用、`pytest` 全绿。

| 阶段 | 内容 | 完成标准（done when） |
|---|---|---|
| 0 | **冻结基线。** 用脚本生成小夹具：PDF、EPUB、docx、md 各一份，都含 1 张图、1 张表、1 个标题；用 `FakeBackend` 记录现有 PDF→PDF、EPUB→PDF 的页数、每页文字、后端调用次数 | `tests/test_baseline.py` 在现有代码上通过；夹具生成脚本入库 |
| 1 | 新增 `model.py`、`store.py`（含资源目录、哈希、`schema`、旧缓存迁移），不接入流程 | 往返（存→读）测试通过；迁移测试通过；`test_architecture` 通过 |
| 2 | PDF 读取器产出 `Document`（含图、表、标题类型）；`translate_units` 接入；PDF 写入器改为从 `Document` 取块 | 阶段 0 基线全部不变；同一本书第二次运行后端调用 0 次；旧 PDF 缓存迁移成功 |
| 3 | EPUB/TXT 读取器（结构保留，不再 `paginate`）；文本页写入器从块生成 | EPUB→PDF 基线文字内容不变；输出的 PDF 里多出表和图（新增断言） |
| 4 | 定下 `Writer` 接口和注册表；写 EPUB 写入器（同格式回写 + 跨格式新建） | EPUB→EPUB 双语输出能被 `ebooklib` 读回，块序列与输入一致，原图与 CSS 仍在 |
| 5 | Markdown 读取器 + 写入器 | md→md、md→pdf、pdf→md 的往返测试通过 |
| 6 | docx 读取器 + 写入器（新依赖获批后） | docx 与其他三种格式的往返测试通过 |
| 7 | 入口层：`JobOptions.output_format`（`--to`）、`default_output` 按格式给扩展名、Web/桌面的上传扩展名列表和输出文件名、界面文案 | 4×4 矩阵测试全部通过；`web/jobs.py`、`web/app.py` 不再写死 `output.pdf` |
| 8 | 清理：删除 `read_book` 的页列表接口、旧 `cache_key` 写入路径（读取迁移保留）、`make_pdf` 的旧签名；重生成 `docs/dependency-graph.md`、`docs/THIRD_PARTY.md` | `grep` 无旧接口引用；全部测试通过；依赖图无环 |

阶段 2 是风险最大的一步（缓存格式、翻译流程、PDF 渲染同时动），合并前要在一本真实的书上手工比对。

## 6. 验证方案

- **黄金文件测试（自动）：** 对 4 种输入夹具 × 4 种输出 × 2 种模式共 32 个组合，不比字节，而是用我们自己的读取器把输出读回 `Document`，断言：块类型序列正确、图块数和表块数等于输入、译文出现在对应原文之后（`FakeBackend` 的译文 `译n` 便于对位）。
- **缓存命中不调用后端：** 先跑 A→B，再跑 A→C（换输出格式）和 A→B（原样重跑），断言 `FakeBackend.calls` 在后两次为空。另测：改一块原文，只有这一块被重译。
- **迁移测试：** 旧格式缓存 → 新格式，断言零后端调用；对不上的页被标为待译。
- **同格式版式（手工清单，沿用 `docs/MANUAL_TEST.md` 的做法）：** ① PDF→PDF 对比原页，译页的块位置、字号、表格列位置与原页一致；② 含图页的图没有被擦掉或错位；③ 扫描页仍能用 `ink_layer` 出干净页；④ EPUB→EPUB 在 Apple Books 和一个阅读器里打开，目录、封面、图片、CSS 正常；⑤ CJK 和阿拉伯语输出无方框字；⑥ Word 里打开 docx 无"修复"提示。

## 7. 风险

| # | 风险 | 应对 |
|---|---|---|
| R-1 | **扫描/仅 OCR 的 PDF：** 文字来自 OCR，无结构，图靠整页图像；跨格式输出时图的处理 | 第一版：扫描页的文字块照常输出，页面里的图不单独抽取（可选"嵌入整页图像"，待定）。OCR 结果写进块，不再用 `.ocr.json` |
| R-2 | **多栏 PDF 的阅读顺序：** `extract_blocks` 按 pymupdf 默认顺序，多栏、侧栏、页眉页脚会乱序；版式复刻不受影响（靠 bbox），但跨格式输出会读起来错乱 | 读取器增加按栏排序（`sort=True` 或自写栏检测）和页眉页脚去除；先用一本多栏论文做夹具；做不好就在文档里写明限制 |
| R-3 | **公式：** PDF 里没有可靠的公式检测；EPUB 的 MathML、docx 的 OMML 无法转成别的格式 | 低字母占比的块标为 `formula`，不翻译；能截图就存图，否则保留原文 |
| R-4 | **脚注、页眉页脚、跨页段落：** PDF 逐页处理，跨页的句子被切成两块 | 沿用现有上下文机制（`ctx`）改善译文；块本身不合并，输出时不强求连贯 |
| R-5 | **CJK/RTL 字体：** PDF 用 pymupdf 内置字体已能处理（见 `writer.py` 文件头）；docx 和 EPUB 依赖阅读器自带字体，可能出方框 | docx 设东亚/复杂文种字体名和 `bidi`；EPUB 设 `lang`/`dir`，不嵌字体；列入手工清单 |
| R-6 | **docx/EPUB 解析有损：** 行内格式、文本框、批注、修订、嵌套表丢失；译文块没有行内格式 | 双语模式保留原文块；报告里列出"读取时降级的元素数"，让用户知道丢了什么 |
| R-7 | **矢量图/图表截取不准：** 截到文字或截不全 | 先只支持内嵌位图 + 明确的矢量绘图区域，用夹具验证；不准的退回"不输出该图并记一条警告" |
| R-8 | **文档缓存体积：** 394 页的书带图，资源目录可能几十 MB | 资源按哈希去重，图片 JPEG/PNG 原样存；设大小上限并在 UI 提示（待定） |
| R-9 | **阶段 2 一次改动过大** | 阶段内再拆提交；保留旧路径到阶段 8 才删 |

## 8. 与 refactoring-plan.md 的关系

- **R2（`JobOptions`）和 R3（`complete` 移出 `translate`）已经完成**（提交 `7375d2f`、`32ead65`），`refactoring-plan.md` 里关于它们的描述已经过时。本计划在 `JobOptions` 上增加 `output_format`，不冲突。
- **`pipeline.py`、`translate.py` 重叠：** R2/R3 改过的就是这两个文件。本计划会大幅改写 `translate_all`、`translate_book`、`glossary_changes`。**建议先做本计划，再回头评估 R5**（`web/app.py` 与 `web/jobs.py` 的职责划分），因为阶段 7 会改这两个文件里的 `output.pdf`、`EXTENSIONS`；R4（桌面壳）与本计划基本无关，可独立进行。
- **R1（中英文页面合并）** 与本计划无关；阶段 7 要改的界面文案会落在 R1 前后的两种页面形式上，**如果打算做 R1，最好先做**，否则同一处文案要改两份。
- **直接冲突一处：** `refactoring-plan.md` §6 写"不在本次范围：大规模目录重组"。本计划把 `readers.py`、`writer.py` 变成包，是功能需要，不是整理；这一点以本计划为准。
- `docs/dependency-graph.md`、`tests/test_architecture.py` 要随阶段 1、8 更新。

## 9. 假设

- Word 指 `.docx`，不含旧 `.doc`。
- Markdown 输入可以含图片和表格。
- 跨格式的保真标准是"内容相同、顺序相同、含图和表"，不是像素或样式一致。
- **我对你的清单做了一处补充：** 现有代码支持 `.txt` 输入，保留它（成本很低），但不作为输出格式。如果你想去掉，告诉我。
- 读代码后发现不成立的假设：见第 2 节末——"原文已存在缓存里"并不成立。

## 10. 待定事项（每项给出默认建议）

1. **旧缓存对不上时是否接受重新付费？** 建议：接受，但迁移前在界面/命令行提示"约 N 页需要重译"，并允许 `--keep-legacy` 跳过。
2. **新增依赖 python-docx 和 markdown-it-py？** 建议：同意；MIT 许可，先跑 `packaging/third_party.py` 核对。替代方案：docx 手写 zip + XML（工作量大、易错），Markdown 用 `mistune`。
3. **默认输出格式？** 建议：保持 PDF（不改变现有行为），新增 `--to {pdf,epub,docx,md}`；以后再考虑"默认同输入格式"。
4. **DOCX→DOCX 是否要保留原版式？** 建议：第一版不做（走跨格式路径），用户要求时再加回写（类似 EPUB 的做法）。
5. **扫描 PDF 转其他格式时，是否嵌入整页图像？** 建议：默认不嵌，只输出 OCR 文字；加一个选项。
6. **译文是否保留行内格式（粗体、链接）？** 建议：Markdown 保留（模型处理标记），EPUB/docx 第一版只保留块级格式。
7. **文档缓存的位置与命名：** 建议：`<state>.book.json`、`<state>.tr.<target>.json`、`<state>.assets/`，与现有 `<state>.cache.json` 并列；Web 端要显式传 `state`，不能再从 `output.pdf` 推导。
