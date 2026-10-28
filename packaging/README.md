# 独立应用构建

最终用户不需要 Python、Node、Codex、Microsoft Excel 或独立安装 Tesseract。
OCR 引擎、英文/数字识别模型、图形界面及 Excel/PDF 依赖都随应用分发。

- Windows 10/11 x64：`LabelDesk-0.5.0-Windows-x64-Setup.exe`，安装到当前用户目录，包含开始菜单和桌面快捷方式；另提供便携 ZIP。
- Apple 芯片 Mac：DMG 内拖动 LabelDesk 到 Applications。当前本机构建使用的 OCR 库要求 macOS 26+；GitHub Actions 配置在 macOS 14 arm64 构建，须运行成功后才能确认兼容性。
- 应用目前没有商业代码签名证书/Apple Developer ID 公证，不能承诺首次下载打开没有系统验证提示。

## GitHub Actions

将本项目源码放在私有仓库根目录。工作流 `.github/workflows/build-desktop.yml` 在 main 分支的相关源码更新时构建，也可通过 Actions → Build desktop installers → Run workflow 手动运行。成功后从 Artifacts 下载对应平台安装包。不会上传生产 PDF 或用户导出文件。

工作流运行单元测试，随后执行打包后的 `--self-test`：实际 OCR、Excel 写入读取、原生矢量 PDF 汇总、Excel 顺序汇总、Tk/CustomTkinter 控件。测试失败不会上传安装包。Windows 构建机自动安装 Tesseract 和 Inno Setup；这些只用于构建，最终用户无需安装。

本地构建：Windows 开发机运行 `packaging/build_windows.ps1`；Apple 芯片开发机安装 Python 3.12、Tesseract 后运行 `bash packaging/build_mac.sh`。可用 LABELDESK_TESSERACT、LABELDESK_TESSDATA 指定构建机 OCR 目录，用 LABELDESK_MIN_MACOS 指定与所用原生库匹配的最低系统版本。

所有第三方组件许可证收集到安装包 licenses 目录；PyMuPDF 等组件的许可证随包提供，分发时一并提供相应项目源码。
