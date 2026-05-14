import os
import sys
import json
import argparse
import asyncio
import random

import aiohttp
import qrcode
from bilibili_api import user
from bilibili_api.utils.network import Credential
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

# Windows 下 MSYS2/Cmd 可能使用 GBK 编码，强制 UTF-8 以支持二维码和 emoji 输出
sys.stdout.reconfigure(encoding='utf-8')

CREDENTIAL_FILE = os.path.join(os.getcwd(), ".bili_credential.json")


def load_credential() -> Credential | None:
    if os.path.exists(CREDENTIAL_FILE):
        with open(CREDENTIAL_FILE) as f:
            data = json.load(f)
        return Credential.from_cookies(data)
    return None


def save_credential(credential: Credential):
    with open(CREDENTIAL_FILE, 'w') as f:
        json.dump(credential.get_cookies(), f)


def load_failed(failed_file: str) -> set:
    if os.path.exists(failed_file):
        with open(failed_file) as f:
            return set(json.load(f))
    return set()


def save_failed(failed_file: str, urls: set):
    if urls:
        with open(failed_file, 'w') as f:
            json.dump(list(urls), f)
    elif os.path.exists(failed_file):
        os.remove(failed_file)


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


async def download(session: aiohttp.ClientSession, url: str, path: str,
                   failed: set, semaphore: asyncio.Semaphore, delay: float):
    async with semaphore:
        try:
            async with session.get(url=url) as response:
                filename = url.split('/')[-1]
                filepath = os.path.join(path, filename)
                if os.path.exists(filepath):
                    return
                with open(filepath, 'wb') as f:
                    while True:
                        chunk = await response.content.read(1024)
                        if not chunk:
                            break
                        f.write(chunk)
        except:
            failed.add(url)
        await asyncio.sleep(delay)


def dict2urls(data: dict):
    res = {"pics": []}
    for item in data["items"]:
        major = item["modules"]["module_dynamic"]["major"]
        if major and "opus" in major:
            opus = major.get("opus")
            if opus:
                pics = opus.get("pics")
                if pics:
                    res["pics"] += [pic["url"] for pic in pics]
    return res


async def download_batch(session: aiohttp.ClientSession, urls: list, path: str,
                         failed: set, semaphore: asyncio.Semaphore, delay: float):
    tasks = [download(session, url, path, failed, semaphore, delay)
             for url in urls]
    await asyncio.gather(*tasks)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('uid', type=int)
    parser.add_argument('--path', default='pics')
    parser.add_argument('--login', action='store_true', help='强制重新扫码登录')
    parser.add_argument('--delay', type=float, default=0.3, help='图片下载间隔/秒 (默认0.3)')
    parser.add_argument('--concurrency', type=int, default=3, help='并发下载数 (默认3)')
    parser.add_argument('--page-delay', type=float, default=1.5, help='翻页间隔/秒 (默认1.5)')
    args = parser.parse_args()

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
    path = os.path.join(args.path, str(args.uid))
    os.makedirs(path, exist_ok=True)

    failed_file = os.path.join(path, "failed_urls.json")
    failed = load_failed(failed_file)
    semaphore = asyncio.Semaphore(args.concurrency)

    offset = ""
    total = 0
    print("----downloading----")
    async with aiohttp.ClientSession() as session:
        while True:
            res = await u.get_dynamics_new(offset)
            urls = dict2urls(res)["pics"]
            if urls:
                await download_batch(session, urls, path, failed, semaphore, args.delay)
                total += len(urls)
                print(f"  本页 {len(urls)} 张，累计 {total} 张")

            if not res["has_more"]:
                break
            offset = res["offset"]
            # 翻页前随机延迟，避免触发风控
            await asyncio.sleep(args.page_delay + random.uniform(0, 1))

    retry_count = 0
    while failed and retry_count < 3:
        retry_count += 1
        print(f"----重试失败图片 第{retry_count}次 ({len(failed)} 张)----")
        urls = list(failed)
        failed.clear()
        async with aiohttp.ClientSession() as session:
            await download_batch(session, urls, path, failed, semaphore, args.delay)
        if failed:
            await asyncio.sleep(2)

    print(f"----下载完成，共 {total} 张----")
    if failed:
        save_failed(failed_file, failed)
        print(f"----{len(failed)} 张下载失败，已记录到 {failed_file}----")
        for url in failed:
            print(url)
    else:
        save_failed(failed_file, set())


if __name__ == "__main__":
    asyncio.run(main())
