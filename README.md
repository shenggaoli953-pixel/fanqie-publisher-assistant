# 番茄创作发布助手

本地 Windows 工具，用于整理番茄小说章节排程、同步后台状态，并提交小说章节或短故事。它不会修改原始正文，也不会把账号密码上传到本仓库。

## 下载使用

普通用户请在 [Releases](https://github.com/shenggaoli953-pixel/fanqie-publisher-assistant/releases) 下载 `FanqiePublisher-Share.zip`，完整解压后运行：

```text
release\FanqiePublisher\FanqiePublisher.exe
```

首次启动会在解压目录创建 `data` 文件夹，并在工具自己的 Edge 配置中登录番茄账号。

> 当前发布包尚未使用商业代码签名证书。Windows 可能提示来源未知；若 Smart App Control 直接阻止未签名程序，请不要关闭系统安全设置。

## 从源码运行

需要 Windows、Microsoft Edge 和 Python 3.11 或更高版本。

```powershell
git clone https://github.com/shenggaoli953-pixel/fanqie-publisher-assistant.git
cd fanqie-publisher-assistant
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

运行测试：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

## 功能

- 递归读取 `第001章-标题.txt`，上传时自动转为不补零的阿拉伯数字章节号。
- 按每日字数或章节数生成排程，可指定起始日期、起始章节、结束章节和 AI 声明。
- 提交前读取全部后台分页，同步已发布、待发布和缺失章节；本地有章节缺口时停止在缺口前。
- 遇到错别字、格式或继续发布提示时按页面状态继续；平台额度、风险、验证码和页面异常会停止后续提交。
- 支持短故事导入、封面、分类、AI 声明和试读设置；自动分类宁少勿乱，仍可手动选择至多 8 个分类。
- 点击一次“发布全部未发布短故事”后，只同步一次后台已发布标题，跳过已发布作品，并按软件添加顺序连续提交其余作品。

## 数据与账号

运行数据、作品路径、Edge 登录配置和本地排程都保存在 `data/`，该目录被 Git 忽略，不会被提交到 GitHub。每位使用者应使用自己的番茄账号，并自行确认内容、版权和平台规则。

## 打包

```powershell
.\build.ps1
```

产物生成于 `release\FanqiePublisher\`。构建前会运行全部单元测试。

## 开源协议

本项目采用 [MIT License](LICENSE)。
