import os
import re
import sys
import json
import argparse
import asyncio
import random
import shutil
from datetime import datetime, timezone, timedelta

import aiohttp
import qrcode
from bilibili_api import user
from bilibili_api.utils.network import Credential
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

sys.stdout.reconfigure(encoding='utf-8')

CREDENTIAL_FILE = os.path.join(os.getcwd(), ".bili_credential.json")
CST = timezone(timedelta(hours=8))
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\n\r\t]')
MAX_FOLDER_NAME = 50


def load_credential() -> Credential | None:
    if os.path.exists(CREDENTIAL_FILE):
        with open(CREDENTIAL_FILE) as f:
            return Credential.from_cookies(json.load(f))
    return None


def save_credential(credential: Credential):
    with open(CREDENTIAL_FILE, 'w') as f:
        json.dump(credential.get_cookies(), f)


def load_failed(failed_file: str) -> dict[str, str]:
    if os.path.exists(failed_file):
        with open(failed_file) as f:
            data = json.load(f)
            if isinstance(data, list):
                return {url: "" for url in data}
            return data
    return {}


def save_failed(failed_file: str, failed: dict[str, str]):
    if failed:
        with open(failed_file, 'w') as f:
            json.dump(failed, f)
    elif os.path.exists(failed_file):
        os.remove(failed_file)


def save_urls_backup(folder_path: str, urls: list[str]):
    backup_file = os.path.join(folder_path, "urls.txt")
    if not os.path.exists(backup_file):
        with open(backup_file, 'w', encoding='utf-8') as f:
            for url in urls:
                f.write(url + '\n')


def make_folder_name(item: dict) -> str:
    modules = item.get("modules", {})
    author = modules.get("module_author", {}) or {}
    pub_ts = author.get("pub_ts") or author.get("pub_time") or 0
    try:
        date_str = datetime.fromtimestamp(int(pub_ts), tz=CST).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        date_str = "unknown-date"

    dynamic = modules.get("module_dynamic", {}) or {}
    desc = dynamic.get("desc") or {}
    text = ""
    if isinstance(desc, dict):
        text = desc.get("text", "")
    if not text:
        major = dynamic.get("major", {}) or {}
        opus = major.get("opus", {}) or {}
        if isinstance(opus, dict):
            title = opus.get("title") or ""
            summary = opus.get("summary", {}) or {}
            if isinstance(summary, dict):
                text = summary.get("text", "") or title
            else:
                text = title
    text = ILLEGAL_CHARS.sub('', text).strip()
    text = re.sub(r'#(\S+)', r'\1', text)
    text = re.sub(r'\[图片\]|\[image\]|\[emot:[^\]]+\]', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text)
    if len(text) > MAX_FOLDER_NAME:
        text = text[:MAX_FOLDER_NAME]
    text = text.rstrip('. ')
    if not text:
        text = "(无文字)"
    return f"{date_str}_{text}"


def extract_dynamics(data: dict) -> list[dict]:
    result = []
    for item in data.get("items", []):
        major = (item.get("modules", {}).get("module_dynamic", {}) or {}).get("major")
        if not major:
            continue
        opus = (major or {}).get("opus")
        if not opus:
            continue
        pics = (opus or {}).get("pics")
        if not pics:
            continue
        urls = [pic["url"] for pic in pics if pic and pic.get("url")]
        if urls:
            result.append({
                "folder": make_folder_name(item),
                "urls": urls,
            })
    return result


async def download(session: aiohttp.ClientSession, url: str, filepath: str,
                   folder: str, failed: dict[str, str]):
    if os.path.exists(filepath):
        return
    try:
        async with session.get(url=url) as response:
            with open(filepath, 'wb') as f:
                while True:
                    chunk = await response.content.read(1024)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception as e:
        print(f"  [错误] {os.path.basename(filepath)}: {e}")
        failed[url] = folder


async def qrcode_login() -> Credential | None:
    qr = QrCodeLogin()
    await qr.generate_qrcode()
    qr_code = qrcode.QRCode(box_size=1, border=2)
    qr_code.add_data(qr._QrCodeLogin__qr_link)
    qr_code.print_ascii()
    print("请使用B站客户端扫描上方二维码登录")
    while True:
        state = await qr.check_state()
        if state == QrCodeLoginEvents.DONE:
            print("扫码成功！")
            return qr.get_credential()
        elif state == QrCodeLoginEvents.TIMEOUT:
            print("二维码已过期，请重试")
            return None
        elif state == QrCodeLoginEvents.SCAN:
            pass
        elif state == QrCodeLoginEvents.CONF:
            print("已扫描，请在手机上确认登录...")
        await asyncio.sleep(1)


async def download_batch(session: aiohttp.ClientSession, dynamics: list[dict],
                         base_path: str, failed: dict[str, str],
                         semaphore: asyncio.Semaphore, delay: float):
    for dyn in dynamics:
        folder_path = os.path.join(base_path, dyn["folder"])
        for url in dyn["urls"]:
            filename = url.split('/')[-1]
            old_path = os.path.join(base_path, filename)
            new_path = os.path.join(folder_path, filename)
            if os.path.isfile(old_path) and not os.path.exists(new_path):
                os.makedirs(folder_path, exist_ok=True)
                shutil.move(old_path, new_path)

        if not dyn["urls"]:
            continue

        os.makedirs(folder_path, exist_ok=True)
        save_urls_backup(folder_path, dyn["urls"])
        async with semaphore:
            tasks = []
            for url in dyn["urls"]:
                filename = url.split('/')[-1]
                filepath = os.path.join(folder_path, filename)
                tasks.append(download(session, url, filepath, dyn["folder"], failed))
            await asyncio.gather(*tasks)
        await asyncio.sleep(delay)


async def retry_failed_urls(base_path: str, concurrency: int, failed: dict[str, str] | None = None):
    failed_file = os.path.join(base_path, "failed_urls.json")
    if failed is None:
        failed = load_failed(failed_file)
    else:
        # 合并文件中的旧失败记录和内存中的新失败记录
        old = load_failed(failed_file)
        for url, folder in old.items():
            if url not in failed:
                failed[url] = folder
    if not failed:
        print("没有失败记录")
        return
    semaphore = asyncio.Semaphore(concurrency)
    for attempt in range(1, 4):
        print(f"----重试失败图片 第{attempt}次 ({len(failed)} 张)----")
        current = dict(failed)
        failed.clear()
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url, folder in current.items():
                filename = url.split('/')[-1]
                filepath = os.path.join(base_path, folder, filename) if folder else os.path.join(base_path, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                tasks.append(download(session, url, filepath, folder, failed))
            await asyncio.gather(*tasks)
        if not failed:
            print("全部重试成功！")
            break
        await asyncio.sleep(2)
    if failed:
        save_failed(failed_file, failed)
        print(f"----{len(failed)} 张仍失败，已更新 {failed_file}----")
        for url, folder in failed.items():
            print(f"  [{folder}] {url}")
    else:
        save_failed(failed_file, {})


def find_failed_files(root_path: str) -> list[str]:
    """扫描 root_path 下所有 uid 目录里的 failed_urls.json"""
    result = []
    if not os.path.isdir(root_path):
        return result
    for entry in os.listdir(root_path):
        uid_dir = os.path.join(root_path, entry)
        if os.path.isdir(uid_dir):
            f = os.path.join(uid_dir, "failed_urls.json")
            if os.path.isfile(f):
                result.append(f)
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('uid', type=int, nargs='?', help='up 主的 UID（--retry-failed 时可省略）')
    parser.add_argument('--path', default='pics')
    parser.add_argument('--login', action='store_true', help='强制重新扫码登录')
    parser.add_argument('--delay', type=float, default=0.3, help='动态间下载延迟/秒')
    parser.add_argument('--concurrency', type=int, default=1, help='并发动态数')
    parser.add_argument('--page-delay', type=float, default=1.5, help='翻页间隔/秒')
    parser.add_argument('--retry-failed', action='store_true', help='仅重试失败文件中的图片')
    args = parser.parse_args()

    if args.retry_failed:
        if args.uid:
            base_path = os.path.join(args.path, str(args.uid))
            await retry_failed_urls(base_path, args.concurrency, None)
        else:
            failed_files = find_failed_files(args.path)
            if not failed_files:
                print(f"在 {args.path} 下没有找到失败记录")
                return
            for ff in failed_files:
                uid_dir = os.path.dirname(ff)
                print(f"\n=== 重试 {uid_dir} ===")
                await retry_failed_urls(uid_dir, args.concurrency, None)
        return

    if args.uid is None:
        parser.error("请提供 uid，或使用 --retry-failed")

    credential = None if args.login else load_credential()
    if credential is None:
        print("⚠ 未登录状态下可能无法获取全部动态")
        ans = input("是否使用二维码登录？[y/N] ").strip().lower()
        if ans in ('y', 'yes'):
            credential = await qrcode_login()
            if credential:
                save_credential(credential)
            else:
                print("登录失败，将以未登录状态继续")
        else:
            print("将以未登录状态继续，可能无法获取全部动态\n")

    u = user.User(uid=args.uid, credential=credential)
    base_path = os.path.join(args.path, str(args.uid))
    os.makedirs(base_path, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)

    failed_file = os.path.join(base_path, "failed_urls.json")
    failed = load_failed(failed_file)

    offset = ""
    total = 0
    print("----downloading----")
    async with aiohttp.ClientSession() as session:
        while True:
            res = await u.get_dynamics_new(offset)
            dynamics = extract_dynamics(res)
            if dynamics:
                await download_batch(session, dynamics, base_path, failed,
                                     semaphore, args.delay)
                page_total = sum(len(d["urls"]) for d in dynamics)
                total += page_total
                print(f"  本页 {len(dynamics)} 条动态 / {page_total} 张图，累计 {total} 张")

            if not res["has_more"]:
                break
            offset = res["offset"]
            await asyncio.sleep(args.page_delay + random.uniform(0, 1))

    await retry_failed_urls(base_path, args.concurrency, failed)
    print(f"----下载完成，共 {total} 张----")


if __name__ == "__main__":
    asyncio.run(main())
