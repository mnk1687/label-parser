# LabelDesk v0.9.0 · 生产标签组合

新版流程：**整批 PDF → ProdSheet 排序明细 Excel → TXT1 文件夹 → 以 TXT2 命名的单条 Barcode 组合 PDF**。

## 界面和操作

关闭旧窗口，双击 `启动解析工具.command`。界面改为浅色、简约布局：左侧导入与批次切换，中间生产明细，右侧整页组合预览和关联来源。

1. 一次导入 ProdSheet、MAIN、CARE，以及可选的 COMPO1、COMPO2、COMPO3，或选择整批文件夹。
2. 自动读取 ProdSheet 的 Article、Size、TXT1、TXT2、Barcode、Quantity。TXT2 跨页换行会补全。
3. 明细按 TXT1、颜色、尺码排序。可搜索 TXT1、TXT2、Barcode，或筛选一个 TXT1。
4. 点击某条明细，右侧直接预览**最终组合页**；切换“关联来源”查看同条 Barcode 的具体源文件及页码。
5. 点击首列复选框选择明细，或“勾选当前筛选”选择当前款号/搜索结果；不会默认勾选全部。
6. “导出排序 Excel”可单独保存完整明细；“导出所选组合”先生成并重新读取完整排序 Excel，再按 Excel 中选中 Barcode 对应的 TXT1 和 TXT2 产出 PDF。

## ProdSheet 稳定性校验

导入时默认先读取 PDF 文字层，遇到跨列连读时按字符实际坐标拆回列；随后将页面渲染为图片，对 Article、Size、TXT1、TXT2、Barcode、Quantity 分列 OCR 复核。首次 300 DPI 不一致时以 450 DPI 重试。OCR 结果不会覆盖原始 PDF 字段。

- 条码和数量逐项比较，保留行顺序；不是把所有数字拼接后比较。
- 仅对已知款号、Article 编号内的 `O/0`、`I/L/1` 字形差异做有限比对，记录为 `matched-code-glyphs`；不修改原数据，不把此规则用于颜色、尺码、条码或数量。
- **PDF 文字层是第一证据，OCR 是第二证据，用户确认是最终证据。** 差异不会静默覆盖 PDF，也不会直接打断导入：批次照常加载，差异汇总为“待确认”项。
- 导出前只做一次汇总确认：列出差异条数、高风险项和前 10 条明细；用户确认后按 PDF 文字层/当前解析值继续导出，并把全部差异写入 `生成核对报告.json/.txt`。
- 核对完整明细数、页脚 Items、Quantity 合计、页脚 Total Order、TXT2 续行和尺码；这些差异默认进入待确认列表。
- 仍会硬阻断的只有内部矛盾且没有可选值的情况：同一批次出现重复条码，或 PDF 条码的 EAN-13 校验位不正确；以及导出后回读核对失败。
- 文字层缺失或不含 TXT1 表头时使用整页 OCR；该页所有字段标记为 OCR 来源，并在摘要与报告中提示。整页 OCR 仍可能误读，操作员确认前应核对原单，优先取得原生 PDF。
- `ProductionBatch.verification` 保留 PDF/OCR 对比证据（OCR 页标记为 `整页OCR/OCR`，不冒充 PDF 文字层）；`validation_errors` 只保留硬阻断原因；`review_items` 保存待确认差异；`ocr_pages` 记录退化为整页 OCR 的页号。底层 `read_prodsheet(..., verify_ocr=False)` 供单元测试和仅文字层诊断使用；应用的 `discover()` 默认开启完整复核。

生成后执行第三重核对：重新读取落盘 Excel，与 ProdSheet 保存的页脚 `Items` / `Total Order` 比较，并逐条检查条码与 Quantity，防止总数相同但有重复/遗漏。重新打开单条、汇总及分类 PDF，核对页数、顺序和渲染内容。成功后在输出目录写入 `生成核对报告.txt` 和 `.json`，并显示原单条数/总数量、本次导出条数/数量。部分勾选明确列出未勾选条数和数量；不会将 Quantity 当作 PDF 页数，也不会因每种分类各有一份 PDF 而重复累加生产数量。生成后核对通过，或差异已由操作员确认后，才显示完成；失败保留失败报告供检查。单独导出 Excel 时也会回读核对并保存同名核对报告。

左侧“清除全部导入数据”清空全部批次、勾选、筛选、预览和输出目录引用，保留磁盘源文件及导出结果。处理任务时禁用清除和批次切换。

可重复执行实际文件审查（报告写到指定目录，不改源文件）：

```sh
python -m scripts.review_prodsheets --root . --output /tmp/prodsheet-review.json --with-labels
```

脚本读取根目录下各批次的 ProdSheet，执行双路校验；`--with-labels` 额外检查真实标签关联和组合完整性，并验证源文件哈希。它不导出业务文件。

## 分类排序页签（v0.6）

在上方切换“组合导出 / 分类排序”，共用已识别批次和勾选明细，无需重新 OCR。

分类排序页签右侧可选择 COMPO1、COMPO2、COMPO3、MAIN、CARE，并翻页查看六个一页的实际排版。未勾选时预览当前筛选结果；勾选后预览全部已勾选明细。点击“导出分类排序 PDF”生成独立目录，仅为实际存在的标签类型生成 PDF（缺失的 COMPO 不再生成空白文件）：

```text
批次名_分类排序_时间戳/
├── ProdSheet_排序明细.xlsx
├── compo1排序PDF.pdf
├── compo2排序PDF.pdf
├── compo3排序PDF.pdf
├── main排序PDF.pdf
└── care排序PDF.pdf
```

每个 PDF 分别包含该类型标签，严格跟随本次 Excel 中选中行的顺序。A4 纵向、2 列 × 3 行，先左后右、再从上到下；最后一页不足六个时留空。不会按 Quantity 复制标签。保持完整裁切、原尺寸和原 PDF 对象，原有图片保持原图，预览图不参与导出。某个明细没有某个 COMPO 时保留空位，以维持各分类页的行对齐；MAIN/CARE 缺失、标签重复或尺寸超过单元格时停止，避免缩小、截断或静默跳过。

本批次实测：每类 390 个标签、65 页，共五份 PDF；包含逐条 TXT2 书签。分类导出不生成五联组合 PDF，原组合页签仍保留原输出流程。

## 输出结构

```text
ALT-SS27-016_时间戳/
├── ProdSheet_排序明细.xlsx
├── 排序汇总/
│   └── Excel顺序组合汇总.pdf
├── FBL015-161-02/
│   ├── FBL015-161-02-LT BLUE-25.pdf
│   ├── FBL015-161-02-LT BLUE-26.pdf
│   └── …
└── FBL015-166-03/
    ├── FBL015-166-03-BLACK-25.pdf
    ├── FBL015-166-03-BLACK-26.pdf
    └── …
```

- 文件夹名 = TXT1；PDF 文件名 = 同行 TXT2，不再附加来源文件名或随机后缀。
- 一条 Barcode = 一个 PDF = 一页组合。不同颜色、尺码保持独立。
- 每个 TXT1 文件夹额外生成 `TXT1汇总PDF.pdf`，例如 `FBM015-099-03汇总PDF.pdf`。只汇总本次勾选的组合，颜色分组内尺码从小到大，每个组合占一页，并附 TXT2 书签。直接合并原 PDF 页面，保留原有矢量和图片对象。
- `排序汇总/Excel顺序组合汇总.pdf` 将本次所有勾选的组合放入同一个 PDF，严格跟随生成的 Excel 有效明细行顺序（跳过空白分隔行和未勾选行），不再按文件名或款号重新排序。每条明细一页，保留矢量对象及 TXT2 书签。
- Quantity 保留在 Excel 中，不按数量重复生成 PDF。
- TXT2 中只有系统禁止的文件名字符会替换为下划线；如替换后同名，停止并报告，不静默覆盖。
- 多批次各自导出，原始文件不修改，不生成 JSON 下载文件。

## 固定组合版式

按用户提供的 `未标题-7.pdf`：页面 612 × 792 pt（Letter），各标签保持源尺寸。

| 左列 | 右列 |
| --- | --- |
| MAIN | COMPO3 |
| COMPO2 | CARE |
| COMPO1 | 留空 |

五个位置都对应**同一个 TXT1、同一个 Barcode**。不按相同页码或图片位置猜测。

**自适应组合：MAIN、CARE 为必需来源；COMPO1–COMPO3 为可选来源，可以没有，也可以同时有多个。** 只要 MAIN 和 CARE 各有唯一匹配即可开始组合；缺少的标签会被跳过，其余标签按参考版式的阅读顺序（从左到右、从上到下）自动向前补位，不留空位；五类齐全时仍与原固定版式完全一致。源文件中存在但该 Barcode 没有对应 COMPO 标签时也自动跳过。缺少 MAIN 或 CARE、必需标签匹配不唯一，或 COMPO 匹配到多条时，该明细显示“待检查”，不导出不完整组合。全空白的 COMPO 联仍保留原稿。

## 原生 PDF 内容保留

组合通过 PDF 页面内容引用与视口裁切完成，不再把全部标签渲染成 PNG 后重新写回 PDF。

- 原有文字、线条、矢量图形继续使用原 PDF 对象。
- 原稿中的图片继续使用原图；图片不能因此变成真正的矢量。
- 不重绘字体、二维码，不替换颜色，不缩放标签，不修改源 PDF。
- 界面预览会临时渲染图片用于显示，但导出的 PDF 不经过该预览图。

本批次 COMPO1、COMPO2 本身包含图片内容，其余部分有原生 PDF 文字/图形。输出不会承诺将原图自动转为矢量。

## Excel 明细

列顺序与参考截图一致：Article、Size、TXT1、TXT2、Barcode、Quantity。按 TXT1 → 颜色 → 尺码排序，不同款号/颜色组之间留空行。冻结标题及前三列，Barcode 保留完整 13 位原值，不转为科学计数法显示。

Excel 是本次导出的中间明细：程序会先写出，再重新读取，依据其中 TXT1 建目录、TXT2 命名。当前 UI 尚不提供导入人工修改后的 Excel 功能。

Excel 写入由内置的 openpyxl 完成，不依赖 Node 或外部 Excel 运行时。

## 验证结果

- ProdSheet 17 页、390 条明细、32 个 TXT1，Quantity 合计 35,679。
- 五份标签文件全部匹配；390 个 Barcode 均可组成完整的五联页面。
- 组合样张已与参考排布进行视觉对照。Excel 前 20 行已渲染检查，条码完整显示。
- 导出测试检查一页 PDF、原生矢量对象保留、TXT1/TXT2 路径命名、同条码组合、缺失标签阻止导出。
- GUI 检查两种窗口尺寸下按钮可见，测试“勾选明细 → Excel → TXT1 文件夹 → TXT2 PDF”的完整流程。
- 源文件在实际批量导出前后进行 SHA256 核对，不发生修改。

## 运行

需要 Python 3.10+、Tkinter、CustomTkinter、PyMuPDF 和 OCR 所需的 Tesseract。开发环境可按以下方式安装依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m label_parser --gui
.venv/bin/python -m label_parser '/路径/批次文件夹' --models FBL015-166-03 --output-dir '/路径/成品'
.venv/bin/python -m label_parser '/路径/批次文件夹' --all --output-dir '/路径/成品'
.venv/bin/python -m unittest discover -s tests -v
```

同一个文件夹只应包含一份 ProdSheet 和本批次标签文件，多批次放在各自子文件夹中。识别缓存依旧可用，源内容和规则变化后自动失效。当前适配此 ProdSheet 表格与青色边框标签，其他版式需进一步适配。

## 应用内升级

左侧栏底部显示当前版本和“检查更新”。启动 4 秒后会自动静默检查一次 GitHub 最新 Release；发现新版本时按钮变为“新版本 x.y.z”，点击可查看更新说明并下载安装，也可随时手动点击检查。不联网或 GitHub 不可达时只提示一次，不影响本地解析和导出。

- 只读取 `mnk1687/label-parser` 的正式 Release（`/releases/latest`），测试版和草稿不会推送；下载走 Release 的 HTTPS 地址，文件先写成 `.part`，长度校验通过后才改名生效。
- Windows 下载 `-Setup.exe` 后启动安装程序并退出应用，安装程序原地覆盖升级并保留用户数据。
- macOS 下载 `.dmg`，挂载后把 `LabelDesk.app` 复制回原安装位置，然后重新启动。若应用从只读 dmg 直接运行或没有写入权限，会提示手动拖入“应用程序”。
- 安装包保存在 `~/Downloads`（没有该目录时用系统临时目录），失败可手动运行。
- v0.7.0 及更早版本没有内置升级模块，需要手动安装一次 v0.8.0；之后即可在应用内升级。
- 未登录的 GitHub API 每个 IP 每小时 60 次，办公室多人同时检查仍远超实际用量。

## 构建与发布

PyInstaller 不能跨平台打包，必须在目标系统上构建。版本号只在 `label_parser/__init__.py` 的 `__version__` 维护；`pyproject.toml`、PyInstaller spec、Inno Setup 脚本和产物文件名都从它读取，升版本只改一处。

- 本机构建：Windows 运行 `packaging/build_windows.ps1`（需 Python 3.12 x64、Tesseract、Inno Setup 6），Apple 芯片 Mac 运行 `bash packaging/build_mac.sh`（需 Python 3.12、Tesseract）。细节见 `packaging/README.md`。
- 云端构建：向 `master` 推送相关源码会构建两端安装包并上传 Artifacts；推送 `v*` 标签还会自动创建 GitHub Release 并附上安装包，例如 `git tag v0.9.0 && git push origin v0.9.0`。Release 链接永久有效，支持断点续传。应用内升级只认正式 Release，因此不要把手动创建的 Release 标为 Draft 或 Pre-release。

Windows 产物为 `LabelDesk-<版本>-Windows-x64-Setup.exe`（安装到当前用户目录，无需管理员）和 `LabelDesk-<版本>-Windows-x64-Portable.zip`；macOS 为 `LabelDesk-<版本>-macOS-AppleSilicon.dmg`。两者都没有商业签名，首次运行会出现 SmartScreen / Gatekeeper 提示。
