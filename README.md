# AI Studio（macOS 版）

用本机 ComfyUI + MiniMax H3 出视频、用 H3-Image 出图的网页工作台。重点功能是「系列」：按分组、分集、镜头写好六段式提示词，再逐镜出片，最后自动合成成片。合成时会加上行迹地图动画、字幕、片尾诗文、配音（IndexTTS-2.5）和分离出来的背景配乐。

仓库里附带两个示例系列（只有系列、分集和镜头文字，不含任何成片）：

- **苏东坡 · 一生行迹**：14 集
- **徐霞客 · 游记行迹**：6 集

部署目标是 **Apple Silicon 的 Mac**（例如 M5 Max + 64 GB 统一内存），用 PyTorch MPS 加速，ComfyUI 另装了 Apple Silicon 加速节点。Linux / NVIDIA 版本见 `ai-studio-linux` 仓库。

## 硬件与系统要求

| 项目 | 要求 |
| --- | --- |
| 芯片 | Apple Silicon（M1 及以后；推荐 Max / Ultra） |
| 内存 | 64 GB 统一内存。视频主模型约 14 GB、文本编码器约 14.5 GB、VAE 约 6 GB，配音和分离另需几 GB |
| 硬盘 | 模型约 52 GB，配音模型约 6 GB，再加上成片空间，建议预留 150 GB 以上 |
| 系统 | macOS 15 以上，另需 Xcode 命令行工具和 Homebrew |
| 网络 | 要能访问 GitHub、PyPI、HuggingFace（或 hf-mirror.com）、ModelScope |

## 安装

```bash
# 0. 准备：Xcode 命令行工具 + Homebrew（https://brew.sh）
xcode-select --install

# 1. 取代码（私有仓库：先 brew install gh && gh auth login）
gh repo clone ppyeer/ai-studio-mac ~/ai-studio
cd ~/ai-studio
cp .env.example .env          # 按需修改端口、路径

# 2. 安装 ComfyUI、自定义节点、AI Studio 服务、人声分离、质检、配音环境
bash scripts/install.sh

# 3. 下载模型（可以中断，再次运行会从断点继续）
export HF_ENDPOINT=https://hf-mirror.com   # 国内网络可选
bash scripts/download_models.sh

# 4. 装成登录后自动运行的 launchd 服务
bash scripts/install_services.sh

# 5. 导入示例系列
.venv/bin/python scripts/import_examples.py
```

装好后，用浏览器打开 `http://127.0.0.1:8001/ai-studio`。同一局域网的其他设备用 `http://<这台 Mac 的 IP>:8001/ai-studio` 访问，第一次访问时 macOS 可能会弹窗询问是否允许 Python 接受传入连接，请选「允许」。

`install.sh` 的可选参数：

- `--no-voice`：不装配音
- `--no-tools`：不装人声分离和质检

`download_models.sh` 也可以只下其中一类，例如 `--only video`、`--only image` 或 `--only voice`。

不想装成服务的话，可以开两个终端，分别运行 `bash scripts/run_comfyui.sh` 和 `bash scripts/run_server.sh`。

### 字体

字幕、片尾诗文和地图默认用系统自带的宋体（Songti）。片头诗名和竖排诗句用「隶变」：在「字体册」里搜索「隶变」，点「下载」即可。没有隶变时会用粗宋体代替。

### 让 Mac 一直在线

launchd 服务装在当前用户名下，只在这个用户登录后运行。如果这台 Mac 专门用来出片，建议：

- 在「系统设置 → 用户与群组」里打开自动登录
- 在「系统设置 → 能耗」里关闭自动睡眠
- 或者出片期间运行 `caffeinate -dims` 防止睡眠

## 使用流程（系列）

1. 在「成片库」里新建或打开一个系列，编辑分组（例如「① 初入仕途（1056–1069）」）和分集。
2. 进入分集，按以下顺序操作：
   1. **出片头图**：H3-Image 文生图。
   2. **逐镜出视频**：第 1 镜用片头图作首帧，之后的镜头按「接上一镜」或「新场景」出片。
   3. **配音**：先在「配音设置」里选好旁白音色。音色取自某一条已出视频的原声。然后生成每镜的配音和承上解说。
   4. **合成成片**：依次拼接片头地图、承上解说、各镜、全诗片尾和承上启下，输出 1080P 成片和 SRT 字幕。
3. 每集最新的成片汇总在 `http://127.0.0.1:8001/ai-finals.html`。

视频和图片共用一条渲染队列，同一时间只跑一条任务。服务重启后，没跑完的任务会自动接着跟踪。

## 目录结构

```
server/            AI Studio 服务（Python 标准库 HTTP 服务，无框架）
  server.py          入口，网页和 /api/tools/ai-studio 接口
  ai_studio.py       任务队列、ComfyUI 工作流、系列、合成
  ai_studio_map.py   行迹地图动画（Natural Earth 数据 + 经纬度）
  ai_studio_captions.py  字幕、片头诗名、片尾诗文
  ai_studio_voice.py 配音（在 IndexTTS 的 venv 里运行）
  ai_studio_fonts.py 中文字体查找
  prompt_translate.py 提示词中文对照（可选，Ollama）
  tools/             提示词检查、单条质检、联系表（来自 h3-local-studio，MIT）
web/               前端页面
comfyui-nodes/     需要随仓库分发的 ComfyUI 节点（obvpm：beta57 调度器；H3-Image GGUF 修正）
assets/mapdata/    Natural Earth 1:50m 海岸线、河流、湖泊（公有领域）
examples/          示例系列
scripts/           安装、模型下载、launchd 服务、启动脚本
```

安装后会生成以下目录，都已写进 `.gitignore`：

- `ComfyUI/`：ComfyUI 本体和模型
- `vendor/index-tts/`：配音环境
- `models/`：配音、人声分离和人脸检测模型
- `.venv/`、`.venvs/tools/`：服务和工具的 Python 环境
- `data/`：任务记录、素材库和服务日志

## ComfyUI 组成

| 组件 | 来源 |
| --- | --- |
| ComfyUI v0.45.2 | github.com/comfyanonymous/ComfyUI，自带 MiniMax H3 节点 |
| ComfyUI-GGUF @6ea2651 | github.com/city96/ComfyUI-GGUF，用于 GGUF 主模型和文本编码器 |
| ComfyUI-PlagueKind-Nodes @aaec055 | github.com/PlagueKind/ComfyUI-PlagueKind-Nodes，提供 H3AdaLNLoRAFix |
| ComfyUI-AppleSilicon-FP8 @cfb04c3 | github.com/pawel-mazurkiewicz/ComfyUI-AppleSilicon-FP8，提供 Metal flash-attention、int8 矩阵乘等 MPS 加速 |
| comfyui-obvpm | 随仓库分发（Apache-2.0），提供 beta57 调度器 |
| minimax_h3_image_gguf_fix.py | 随仓库分发（来自 HF Abiray/MiniMax-H3-Image-GGUF），H3-Image GGUF 载入修正 |

ComfyUI 的启动参数在 `.env` 的 `COMFYUI_ARGS` 里，默认是 `--reserve-vram 10 --cache-none --disable-smart-memory`。这组参数会给系统留出余量，每个任务用完就释放模型，避免 64 GB 内存被占满。

模型下载地址见 `scripts/download_models.py`：

- 视频主模型：`Abiray/MiniMax-H3-Pruned-GGUF` 的 FL2VA Q5_K_M
- 加速 LoRA：`Plaguekind/H3-Lora` 的 Parasyte Turbo
- 文本编码器：`realrebelai/MiniMax-H3_GGUFs` 的 qwen3vl-32B Q4_K_M
- VAE：`Comfy-Org/MiniMax-H3` 和 `Comfy-Org/MiniMax-H3-Image`
- 图片主模型：`Abiray/MiniMax-H3-Image-GGUF`
- 配音：ModelScope `IndexTeam/IndexTTS-2.5`

## 常用命令

```bash
launchctl kickstart -k gui/$(id -u)/com.aistudio.server    # 改了 .env 或代码后重启 AI Studio
launchctl kickstart -k gui/$(id -u)/com.aistudio.comfyui   # 重启 ComfyUI
tail -f data/server.log                                    # AI Studio 日志
tail -f ComfyUI/user/ai-studio-comfyui.log                 # ComfyUI 日志（网页上任务旁的终端图标也能看）
bash scripts/install_services.sh --remove                  # 卸载服务
```

## 常见问题

- **页面提示「ComfyUI 缺少视频模型」**：模型还没下完，或者 `COMFYUI_DIR` 指向的目录不对。请重新运行 `bash scripts/download_models.sh`。
- **第一次出片特别慢**：Apple Silicon 加速节点首次启动要编译 Metal 内核，模型也要第一次读进内存，之后会快很多。
- **内存压力大、系统卡顿**：确认 `COMFYUI_ARGS` 里有 `--cache-none --disable-smart-memory`，也可以把 `--reserve-vram` 调大。出片时不要同时跑配音或 Ollama。
- **配音显示「配音环境还没装好」**：确认 `vendor/index-tts/.venv` 存在，并且 `models/IndexTTS-2.5` 已下完（需要运行 `download_models.sh` 时带上配音，默认就会带）。
- **局域网打不开页面**：检查 `.env` 里的 `AI_STUDIO_HOST` 是否为 `0.0.0.0`，以及「系统设置 → 网络 → 防火墙」里是否放行了 Python。

## 安全

服务没有登录鉴权，只适合在可信的内网使用。如果需要从公网访问，请在前面加一层带认证的反向代理，或者通过 VPN 访问。ComfyUI 只监听 127.0.0.1。

## 许可

- 本仓库代码：MIT
- `server/tools/` 来自 [h3-local-studio](https://github.com/zizhongxiao-svg/h3-local-studio)（MIT）
- `comfyui-obvpm`：Apache-2.0
- Natural Earth 数据：公有领域
- MiniMax H3 / H3-Image 模型需遵守 MiniMax 社区许可；公开发布生成的内容时须加 AI 生成标识
- IndexTTS-2.5 模型需遵守 bilibili 模型许可
