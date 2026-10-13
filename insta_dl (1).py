#!/usr/bin/env python3
"""
Instagram Reel downloader using third-party website APIs.
Retries multiple APIs until video is successfully downloaded.
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import os
import time
import sys
import re
import subprocess

REEL_URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.instagram.com/reel/DdK0Y9ismbt"
REEL_ID = re.search(r'/reel/([A-Za-z0-9_-]+)', REEL_URL)
REEL_ID = REEL_ID.group(1) if REEL_ID else "DdK0Y9ismbt"
OUT_DIR = "/home/ubuntu"
MIN_SIZE = 100 * 1024  # 100KB

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

def log(msg):
    print(f"[insta_dl] {msg}", flush=True)

def http_get(url, headers=None, timeout=15):
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', UA)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:
        return 0, b''

def http_post(url, data, headers=None, timeout=15):
    try:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode()
            ctype = 'application/x-www-form-urlencoded'
        elif isinstance(data, str):
            body = data.encode()
            ctype = 'application/json'
        else:
            body = data
            ctype = 'application/x-www-form-urlencoded'
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('User-Agent', UA)
        req.add_header('Content-Type', ctype)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except Exception as e:
        return 0, b''

def download_file(url, dest_path, extra_headers=None):
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', UA)
        req.add_header('Referer', 'https://www.instagram.com/')
        if extra_headers:
            for k, v in extra_headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) >= MIN_SIZE and (data[:4] in (b'\x00\x00\x00\x18', b'\x00\x00\x00\x20', b'ftyp') or data[4:8] == b'ftyp' or data[:3] == b'ID3'):
            with open(dest_path, 'wb') as f:
                f.write(data)
            return True, len(data)
        # relaxed check: just size
        if len(data) >= MIN_SIZE:
            with open(dest_path, 'wb') as f:
                f.write(data)
            return True, len(data)
        return False, len(data)
    except Exception as e:
        return False, 0

def try_snapinsta(reel_url):
    """snapinsta.app - popular Instagram downloader"""
    log("Trying snapinsta.app...")
    try:
        # Step 1: get token from page
        status, html = http_get('https://snapinsta.app/', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        if not token:
            token = re.search(rb'_token.*?value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        # Step 2: POST the URL
        status, resp = http_post('https://snapinsta.app/action.php',
            {'url': reel_url, '_token': tok},
            headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': 'https://snapinsta.app/'})
        if status == 200:
            try:
                j = json.loads(resp)
                html2 = j.get('data', '') or ''
            except:
                html2 = resp.decode(errors='ignore')
            # find video URLs
            links = re.findall(r'href=["\']?(https://[^"\' >]+\.mp4[^"\' >]*)', html2)
            links += re.findall(r'(https://[^"\' >]+\.mp4[^"\' >]*)', html2)
            if links:
                log(f"  snapinsta found {len(links)} link(s)")
                for lnk in links[:3]:
                    dest = os.path.join(OUT_DIR, f"{REEL_ID}_snap.mp4")
                    ok, sz = download_file(lnk, dest)
                    if ok:
                        return dest, sz
        log("  snapinsta failed")
        return None, 0
    except Exception as e:
        log(f"  snapinsta error: {e}")
        return None, 0

def try_sssinstagram(reel_url):
    """sssinstagram.com downloader"""
    log("Trying sssinstagram.com...")
    try:
        status, html = http_get('https://sssinstagram.com/', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        status, resp = http_post('https://sssinstagram.com/request',
            json.dumps({'url': reel_url, 'ts': '', 'tt': ''}),
            headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                     'Referer': 'https://sssinstagram.com/', 'Origin': 'https://sssinstagram.com',
                     'X-CSRF-TOKEN': tok})
        if status == 200:
            try:
                j = json.loads(resp)
                items = j.get('data', {}).get('items', []) or j.get('items', []) or []
                for item in items:
                    url = item.get('url') or item.get('src') or ''
                    if url and '.mp4' in url:
                        dest = os.path.join(OUT_DIR, f"{REEL_ID}_sss.mp4")
                        ok, sz = download_file(url, dest)
                        if ok:
                            return dest, sz
                # fallback: scan raw JSON for mp4 links
                links = re.findall(r'https://[^"\\]+\.mp4[^"\\]*', resp.decode(errors='ignore'))
                for lnk in links[:3]:
                    dest = os.path.join(OUT_DIR, f"{REEL_ID}_sss.mp4")
                    ok, sz = download_file(lnk, dest)
                    if ok:
                        return dest, sz
            except:
                pass
        log("  sssinstagram failed")
        return None, 0
    except Exception as e:
        log(f"  sssinstagram error: {e}")
        return None, 0

def try_igram(reel_url):
    """igram.world Instagram downloader"""
    log("Trying igram.world...")
    try:
        status, html = http_get('https://igram.world/', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        status, resp = http_post('https://igram.world/api/convert',
            json.dumps({'url': reel_url, 'ts': '', 'tt': ''}),
            headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                     'Referer': 'https://igram.world/', 'Origin': 'https://igram.world',
                     'X-CSRF-TOKEN': tok})
        if status != 200:
            status, resp = http_post('https://igram.world/request',
                {'url': reel_url, '_token': tok},
                headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': 'https://igram.world/'})
        if status == 200:
            links = re.findall(r'https://[^"\\> ]+\.mp4[^"\\> ]*', resp.decode(errors='ignore'))
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_igram.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  igram failed")
        return None, 0
    except Exception as e:
        log(f"  igram error: {e}")
        return None, 0

def try_saveinsta(reel_url):
    """saveinsta.app"""
    log("Trying saveinsta.app...")
    try:
        status, html = http_get('https://saveinsta.app/', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        status, resp = http_post('https://saveinsta.app/action.php',
            {'url': reel_url, '_token': tok},
            headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': 'https://saveinsta.app/'})
        if status == 200:
            try:
                j = json.loads(resp)
                html2 = j.get('data', '') or resp.decode(errors='ignore')
            except:
                html2 = resp.decode(errors='ignore')
            links = re.findall(r'https://[^"\' >]+\.mp4[^"\' >]*', html2)
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_si.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  saveinsta failed")
        return None, 0
    except Exception as e:
        log(f"  saveinsta error: {e}")
        return None, 0

def try_inflact(reel_url):
    """inflact.com/tools/instagram-video-downloader"""
    log("Trying inflact.com...")
    try:
        api_url = 'https://downloader.inflact.com/proxy/?url=' + urllib.parse.quote(reel_url)
        status, resp = http_get(api_url, headers={'Referer': 'https://inflact.com/'}, timeout=15)
        if status == 200:
            try:
                j = json.loads(resp)
                media = j.get('media', []) or []
                for item in media:
                    url = item.get('url', '')
                    if url and 'video' in item.get('type', 'video'):
                        dest = os.path.join(OUT_DIR, f"{REEL_ID}_inflact.mp4")
                        ok, sz = download_file(url, dest)
                        if ok:
                            return dest, sz
            except:
                links = re.findall(r'https://[^"\\> ]+\.mp4[^"\\> ]*', resp.decode(errors='ignore'))
                for lnk in links[:3]:
                    dest = os.path.join(OUT_DIR, f"{REEL_ID}_inflact.mp4")
                    ok, sz = download_file(lnk, dest)
                    if ok:
                        return dest, sz
        log("  inflact failed")
        return None, 0
    except Exception as e:
        log(f"  inflact error: {e}")
        return None, 0

def try_instasaved(reel_url):
    """instasaved.net"""
    log("Trying instasaved.net...")
    try:
        status, html = http_get('https://instasaved.net/en', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        status, resp = http_post('https://instasaved.net/en/download',
            {'url': reel_url, '_token': tok},
            headers={'Referer': 'https://instasaved.net/en'})
        if status == 200:
            links = re.findall(r'https://[^"\' >]+\.mp4[^"\' >]*', resp.decode(errors='ignore'))
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_isaved.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  instasaved failed")
        return None, 0
    except Exception as e:
        log(f"  instasaved error: {e}")
        return None, 0

def try_reelsaver(reel_url):
    """reelsaver.net"""
    log("Trying reelsaver.net...")
    try:
        status, html = http_get('https://reelsaver.net/', timeout=10)
        token = re.search(rb'name=["\']_token["\']\s+value=["\']([^"\']+)["\']', html)
        tok = token.group(1).decode() if token else ''
        
        status, resp = http_post('https://reelsaver.net/action.php',
            {'url': reel_url, '_token': tok},
            headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': 'https://reelsaver.net/'})
        if status == 200:
            try:
                j = json.loads(resp)
                html2 = j.get('data', '') or resp.decode(errors='ignore')
            except:
                html2 = resp.decode(errors='ignore')
            links = re.findall(r'https://[^"\' >]+\.mp4[^"\' >]*', html2)
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_rs.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  reelsaver failed")
        return None, 0
    except Exception as e:
        log(f"  reelsaver error: {e}")
        return None, 0

def try_savefrom(reel_url):
    """savefrom.net (same as yt_dl.py success)"""
    log("Trying savefrom.net...")
    try:
        # savefrom uses a simple API endpoint
        api = 'https://worker.sf-tools.com/savefrom.php'
        encoded = urllib.parse.quote(reel_url, safe='')
        post_data = f'sf_url={encoded}&lang=en&app=1'
        
        req = urllib.request.Request(api, data=post_data.encode())
        req.add_header('User-Agent', UA)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        req.add_header('Referer', 'https://en.savefrom.net/')
        req.add_header('Origin', 'https://en.savefrom.net')
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = r.read()
        
        try:
            j = json.loads(resp)
            # look for video URLs in the response
            urls = []
            def extract_urls(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k in ('url', 'src') and isinstance(v, str) and v.startswith('http'):
                            urls.append(v)
                        else:
                            extract_urls(v)
                elif isinstance(obj, list):
                    for i in obj:
                        extract_urls(i)
            extract_urls(j)
            log(f"  Found {len(urls)} link(s)")
            for url in urls[:5]:
                if any(x in url for x in ['.mp4', 'video', 'cdn']):
                    dest = os.path.join(OUT_DIR, f"{REEL_ID}_sf.mp4")
                    ok, sz = download_file(url, dest)
                    if ok:
                        return dest, sz
                    # try without extension filter too
            for url in urls[:5]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_sf.mp4")
                ok, sz = download_file(url, dest)
                if ok:
                    return dest, sz
        except:
            links = re.findall(r'https://[^"\\]+\.mp4[^"\\]*', resp.decode(errors='ignore'))
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_sf.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  savefrom failed")
        return None, 0
    except Exception as e:
        log(f"  savefrom error: {e}")
        return None, 0

def try_rapidapi_insta(reel_url):
    """Try instadownloader via curl subprocess (different UA/headers)"""
    log("Trying instadownloader.app...")
    try:
        result = subprocess.run(
            ['curl', '-s', '-L', '--max-time', '15',
             '-H', f'User-Agent: {UA}',
             '-H', 'Accept: application/json',
             '-H', 'Referer: https://instadownloader.app/',
             f'https://instadownloader.app/api/?url={urllib.parse.quote(reel_url)}'],
            capture_output=True, timeout=20
        )
        resp = result.stdout.decode(errors='ignore')
        try:
            j = json.loads(resp)
            url = j.get('url') or j.get('video') or j.get('video_url') or ''
            if url:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_ida.mp4")
                ok, sz = download_file(url, dest)
                if ok:
                    return dest, sz
        except:
            links = re.findall(r'https://[^"\\> ]+\.mp4[^"\\> ]*', resp)
            for lnk in links[:3]:
                dest = os.path.join(OUT_DIR, f"{REEL_ID}_ida.mp4")
                ok, sz = download_file(lnk, dest)
                if ok:
                    return dest, sz
        log("  instadownloader.app failed")
        return None, 0
    except Exception as e:
        log(f"  instadownloader.app error: {e}")
        return None, 0

def try_yt_dlp(reel_url):
    """Last resort: yt-dlp (may fail due to bot check but worth trying)"""
    log("Trying yt-dlp...")
    try:
        dest = os.path.join(OUT_DIR, f"{REEL_ID}_ytdlp.mp4")
        result = subprocess.run(
            ['yt-dlp', '--no-warnings', '-o', dest, reel_url],
            capture_output=True, timeout=60
        )
        if os.path.exists(dest) and os.path.getsize(dest) >= MIN_SIZE:
            return dest, os.path.getsize(dest)
        log("  yt-dlp failed")
        return None, 0
    except Exception as e:
        log(f"  yt-dlp error: {e}")
        return None, 0

APIS = [
    ('snapinsta.app', try_snapinsta),
    ('sssinstagram.com', try_sssinstagram),
    ('igram.world', try_igram),
    ('saveinsta.app', try_saveinsta),
    ('inflact.com', try_inflact),
    ('instasaved.net', try_instasaved),
    ('reelsaver.net', try_reelsaver),
    ('savefrom.net', try_savefrom),
    ('instadownloader.app', try_rapidapi_insta),
    ('yt-dlp fallback', try_yt_dlp),
]

MAX_ROUNDS = 3

if __name__ == '__main__':
    log(f"Starting download for: {REEL_URL}")
    log(f"Output dir: {OUT_DIR}")
    log(f"Will try {len(APIS)} APIs, up to {MAX_ROUNDS} round(s)")
    
    for round_num in range(1, MAX_ROUNDS + 1):
        log(f"\n=== ROUND {round_num}/{MAX_ROUNDS} ===")
        for name, fn in APIS:
            try:
                dest, sz = fn(REEL_URL)
                if dest and sz >= MIN_SIZE:
                    ftype = subprocess.run(['file', dest], capture_output=True).stdout.decode().strip()
                    log(f"\n✅ SUCCESS! Downloaded to: {dest}")
                    log(f"   File size: {sz:,} bytes ({sz//1024} KB)")
                    log(f"   File type: {ftype}")
                    sys.exit(0)
            except Exception as e:
                log(f"  {name} exception: {e}")
            time.sleep(0.5)
        
        if round_num < MAX_ROUNDS:
            log(f"\nRound {round_num} done, all failed. Waiting 3s before next round...")
            time.sleep(3)
    
    log("\n❌ All providers failed. Try downloading manually or use a browser extension.")
    sys.exit(1)
