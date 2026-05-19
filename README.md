# BiliBiliDynamicDownload

下载哔哩哔哩 up 主所有动态中的图片，按动态自动分组到子文件夹。

## 使用方法

```shell
git clone https://github.com/YoruJiang/BiliBiliDynamicDownload.git
cd BiliBiliDynamicDownload
pip install -r requirement.txt
python main.py <uid> [--path PATH] [--login] [--delay DELAY] [--concurrency N] [--page-delay DELAY]
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uid` | up 主的 UID（必填，`--retry-failed` 时可省略） | - |
| `--path` | 图片保存路径 | `./pics` |
| `--login` | 强制重新扫码登录 | - |
| `--delay` | 动态间下载延迟（秒） | `0.3` |
| `--concurrency` | 并发动态数 | `1` |
| `--page-delay` | 翻页间隔（秒） | `1.5` |
| `--retry-failed` | 仅重试失败记录中的图片，无需 uid | - |

## 目录结构

下载后每个 uid 的图片按动态分组保存：

```
pics/
├── <uid>/
│   ├── failed_urls.json          # 下载失败的图片记录
│   ├── 2024-07-26_动态文字内容/
│   │   ├── urls.txt              # 图片原始链接备份
│   │   ├── xxx.jpg
│   │   └── ...
│   └── 2024-07-25_另一条动态/
│       └── ...
```

## 关于登录

B 站未登录状态下无法获取全部动态。首次运行时会提示是否使用二维码登录：

- 输入 `y`，终端显示二维码，用 B 站 App 扫码即可登录
- 登录凭证会保存在本地，下次运行无需重复扫码
- 输入 `N` 则跳过登录继续运行（可能无法获取全部动态）

## 示例

```shell
# 基本用法
python main.py <uid>

# 指定保存路径
python main.py <uid> --path ./downloads

# 被限流时可以降低请求频率
python main.py <uid> --delay 0.5 --concurrency 2 --page-delay 3

# 重试失败图片（指定 uid）
python main.py <uid> --retry-failed

# 重试所有 uid 的失败图片
python main.py --retry-failed
```
