# 贡献指南 / Contributing Guide

感谢你愿意为 `WW Assist` 做贡献。本项目是基于图像识别的《鸣潮》自动化工具，仅供个人学习与交流使用。提交贡献前，请先阅读[简体中文文档](../zh-CN/index.md)中的免责声明、开发者专区和社区信息。

Thank you for contributing to `WW Assist`. This project is an image-recognition-based automation tool for Wuthering Waves, and is intended only for personal learning and communication. Before contributing, please read the disclaimer, developer section, and community information in the [English documentation](../en/index.md).

## 提交 PR 前 / Before Opening a PR

请先确认你的修改范围：

Please check the scope of your change first:

- Bug 修复、文档修正、翻译修正、小型兼容性修复：可以直接提交 PR。
- 新功能、重构、架构调整、角色逻辑大改、任务行为大改、会显著改变现有功能体验的修改：请在提交 PR 前先联系作者或在社区中讨论，确认方向后再开始或提交。
- 不确定是否属于“大改”的修改：请先联系作者。

- Bug fixes, documentation fixes, translation fixes, and small compatibility fixes: you may open a PR directly.
- New features, refactors, architecture changes, major character logic changes, major task behavior changes, or changes that significantly alter existing behavior: please contact the author or discuss with the community before opening a PR.
- If you are unsure whether a change is major, please contact the author first.

## 联系方式 / Contact

- Discord: [https://discord.gg/vVyCatEBgA](https://discord.gg/vVyCatEBgA)

## 开发环境 / Development Environment

本项目仅支持 Python 3.12。建议使用仓库内的本地虚拟环境运行命令。

This project only supports Python 3.12. Prefer using the repository-local virtual environment when running commands.

```powershell
# 安装或更新依赖 / Install or update dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --upgrade

# 安装固定的运行依赖与测试依赖 / Install pinned runtime and test dependencies
.\.venv\Scripts\python.exe .github/scripts/install_dependencies.py

# 仅进行 Web 测试时需要 / Only for web testing
.\.venv\Scripts\python.exe -m pip install ".[dev,web-test]" --upgrade

# 运行 Release 版本 / Run release version
.\.venv\Scripts\python.exe main.py

# 运行 Debug 版本 / Run debug version
.\.venv\Scripts\python.exe main_debug.py
```

如果没有 `.venv`，可以使用 `python` 代替上面的解释器路径。

If `.venv` does not exist, use `python` instead of the interpreter path above.

## 构建 Windows 便携包 / Build the Windows portable app

默认使用 GitHub Actions 的 Windows 云端机器构建。本机只做日常开发、针对性测试和界面检查。
完整本地打包用于明确要求的离线构建或打包问题复现。

| 入口 | 云端执行内容 | 产物 |
| --- | --- | --- |
| 推送 `workshop-preserved` 或提交 PR | 安装依赖、完整测试 | 测试结果 |
| 手动运行 `Windows Portable` | 完整测试、PyInstaller 打包、独立启动与 OCR 检查 | 测试 ZIP + SHA-256，保留 7 天 |
| 推送 `vX.Y.Z` 或 `vX.Y.Z-beta.N` 等版本标签 | 同上，全部通过后发布 | GitHub Release 的 ZIP + SHA-256 |

手动测试包：

```powershell
gh workflow run build.yml --repo GodRaymond233/xjtu-ww --ref workshop-preserved
gh run list --repo GodRaymond233/xjtu-ww --workflow build.yml --limit 5
```

从对应运行页面的 Artifacts 下载 `windows-portable`。测试包版本包含提交短哈希；
包内 `build-info.json` 记录完整提交、构建运行地址和依赖清单哈希。
手动运行（包括选中标签的手动运行）仅上传产物。正式发布需明确创建并推送版本标签；
稳定版使用 `vX.Y.Z`，预发布使用 `vX.Y.Z-alpha.N`、`vX.Y.Z-beta.N` 或 `vX.Y.Z-rc.N`。

CI 和打包共用依赖安装与测试脚本，同时解析 `requirements.txt` 和项目 extras，
保持运行依赖版本固定。首次安装使用 pip 缓存，失败重试时绕过缓存。
ZIP 上传不再二次压缩；打包失败时上传可用的启动日志和 PyInstaller 警告。

Full builds run on GitHub-hosted Windows runners by default. Branch pushes and PRs run
tests; manual builds produce preview artifacts; version-tag pushes publish releases only
after tests and portable startup/OCR checks pass. Each cloud package records its source
commit and workflow run in `build-info.json`.

需要本地复现打包问题时：

```powershell
.\.venv\Scripts\python.exe .github/scripts/install_dependencies.py --bundle
$env:APP_VERSION = "dev"
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm xjtu-ww.spec
.\.github\scripts\test_portable.ps1
```

构建结果位于 `dist/xjtu-ww`，运行其中的 `xjtu-ww.exe` 直接进入主界面。
发布时压缩整个目录；Python、依赖、OCR 模型和工坊所需角色源码均包含在内。
需要管理员权限进行游戏操作时，请以管理员身份运行。更新时解压到新目录，并复制旧目录的
`configs`、`ok_tasks` 和 `ok_import`（如有）。

The result is `dist/xjtu-ww`; run `xjtu-ww.exe` to open the app. Distribute the entire
directory, which includes Python, dependencies, OCR models, and character sources for
the workshop. Run as administrator when game interaction requires elevation. To update,
extract into a new directory and copy `configs`, `ok_tasks`, and `ok_import`, if present.

## 测试 / Testing

提交 PR 前，请尽量运行相关测试，并在 PR 描述中说明测试结果。

Before opening a PR, please run the relevant tests when possible and include the results in the PR description.

```powershell
.\run_tests.ps1
```

也可以直接运行指定测试：

You can also run a specific test directly:

```powershell
.\.venv\Scripts\python.exe -m unittest tests\TestChar.py
```

## PR 要求 / PR Requirements

- 提交 PR 前，必须使用 AI 审查最终修改，处理审查发现的有效问题，并在 PR 描述中简要说明审查工具、结果及处理情况。
- 保持修改范围清晰，避免把无关格式化、重构和功能修改混在同一个 PR 中。
- 说明改动目的、主要实现方式、影响范围和测试结果。
- 修改用户可见行为时，请补充截图、录屏或清晰的复现说明。
- 修改配置、任务、角色逻辑或识别逻辑时，请说明适用场景和可能影响。
- 不要提交日志、缓存、临时文件、个人配置或无关生成文件。

- Before submitting a PR, have AI review the final changes, address valid findings, and briefly describe the review tool, results, and resolutions in the PR description.
- Keep the PR focused. Avoid mixing unrelated formatting, refactoring, and feature changes in one PR.
- Describe the purpose, implementation, impact, and test results.
- For user-visible behavior changes, include screenshots, recordings, or clear reproduction notes.
- For configuration, task, character logic, or recognition logic changes, describe the applicable scenarios and possible impact.
- Do not commit logs, caches, temporary files, personal settings, or unrelated generated files.

## 添加识别素材 / Adding Recognition Assets

`ok_templates/` 中的源图片和标注直接保存在本仓库中。

Source images and annotations in `ok_templates/` are tracked directly in this repository.

1. 如需添加识别素材，在 WW Assist 的「模板」标签页中添加图片并完成标注。
2. 点击「保存」，保存标注并生成识别素材。
3. 检查生成的修改，将相关的 `ok_templates/` 源图片、标注和 `assets/` 识别素材一起提交。

1. To add recognition assets, add the images and markup in WW Assist's Template tab.
2. Click Save to save the annotations and generate the recognition assets.
3. Review the generated changes and include the relevant `ok_templates/` source images, annotations, and `assets/` recognition assets in the same PR.

## 提交流程 / Submission Flow

1. Fork 本仓库并创建你的功能分支。
2. 完成修改并运行相关测试。
3. 确认是否需要先联系作者，尤其是新功能或大幅修改现有功能。
4. 使用 AI 审查最终修改，处理有效问题并记录结果。
5. 提交 PR，并填写 PR 模板中的所有相关内容，包括 AI 审查结果。
6. 根据维护者反馈调整修改。

1. Fork this repository and create your feature branch.
2. Make the changes and run relevant tests.
3. Confirm whether author contact is needed, especially for new features or major changes to existing behavior.
4. Have AI review the final changes, address valid findings, and record the results.
5. Open a PR and fill in all relevant sections of the PR template, including the AI review results.
6. Update the PR based on maintainer feedback.