# LabelDesk v0.6.0 · 生产标签组合

新版流程：**整批 PDF → ProdSheet 排序明细 Excel → TXT1 文件夹 → 以 TXT2 命名的单条 Barcode 组合 PDF**。

## 界面和操作

关闭旧窗口，双击 `启动解析工具.command`。界面改为浅色、简约布局：左侧导入与批次切换，中间生产明细，右侧整页组合预览和关联来源。

1. 一次导入 ProdSheet、MAIN、CARE、COMPO1、COMPO2、COMPO3，或选择整批文件夹。
2. 自动读取 ProdSheet 的 Article、Size、TXT1、TXT2、Barcode、Quantity。TXT2 跨页换行会补全。
3. 明细按 TXT1、颜色、尺码排序。可搜索 TXT1、TXT2、Barcode，或筛选一个 TXT1。
4. 点击某条明细，右侧直接预览**最终组合页**；切换“关联来源”查看同条 Barcode 的具体源文件及页码。
5. 点击首列复选框选择明细，或“勾选当前筛选”选择当前款号/搜索结果；不会默认勾选全部。
6. “导出排序 Excel”可单独保存完整明细；“导出所选组合”先生成并重新读取完整排序 Excel，再按 Excel 中选中 Barcode 对应的 TXT1 和 TXT2 产出 PDF。

## 分类排序页签（v0.6）

在上方切换“组合导出 / 分类排序”，共用已识别批次和勾选明细，无需重新 OCR。

分类排序页签右侧可选择 COMPO1、COMPO2、COMPO3、MAIN、CARE，并翻页查看六个一页的实际排版。未勾选时预览当前筛选结果；勾选后预览全部已勾选明细。点击“导出五类排序 PDF”生成独立目录：

```text
批次名_分类排序_时间戳/
├── ProdSheet_排序明细.xlsx
├── compo1排序PDF.pdf
├── compo2排序PDF.pdf
├── compo3排序PDF.pdf
├── main排序PDF.pdf
└── care排序PDF.pdf
```

五个 PDF 分别包含该类型标签，严格跟随本次 Excel 中选中行的顺序。A4 纵向、2 列 × 3 行，先左后右、再从上到下；最后一页不足六个时留空。不会按 Quantity 复制标签。保持完整裁切、原尺寸和原 PDF 对象，原有图片保持原图，预览图不参与导出。尺寸超过单元格或标签缺失/重复时停止，避免缩小、截断或静默跳过。

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

五个位置都对应**同一个 TXT1、同一个 Barcode**。不按相同页码或图片位置猜测。匹配不唯一、缺少任一所需来源文件或 Barcode 标签时，该明细显示“待检查”，不导出不完整组合。全空白的 COMPO 联仍保留原稿。

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

## 构建与发布

PyInstaller 不能跨平台打包，必须在目标系统上构建。版本号只在 `label_parser/__init__.py` 的 `__version__` 维护；`pyproject.toml`、PyInstaller spec、Inno Setup 脚本和产物文件名都从它读取，升版本只改一处。

- 本机构建：Windows 运行 `packaging/build_windows.ps1`（需 Python 3.12 x64、Tesseract、Inno Setup 6），Apple 芯片 Mac 运行 `bash packaging/build_mac.sh`（需 Python 3.12、Tesseract）。细节见 `packaging/README.md`。
- 云端构建：向 `master` 推送相关源码会构建两端安装包并上传 Artifacts；推送 `v*` 标签还会自动创建 GitHub Release 并附上安装包，例如 `git tag v0.6.0 && git push origin v0.6.0`。Release 链接永久有效，支持断点续传。

Windows 产物为 `LabelDesk-<版本>-Windows-x64-Setup.exe`（安装到当前用户目录，无需管理员）和 `LabelDesk-<版本>-Windows-x64-Portable.zip`；macOS 为 `LabelDesk-<版本>-macOS-AppleSilicon.dmg`。两者都没有商业签名，首次运行会出现 SmartScreen / Gatekeeper 提示。
