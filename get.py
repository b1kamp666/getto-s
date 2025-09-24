import re
import os
import asyncio
import aiohttp
import random
import subprocess
from aiohttp import ClientTimeout
from tqdm import tqdm

BASE_URL = "https://s.to"
TXT_FOLDER = "backpack"
CONCURRENT_REQUESTS = 5
MIN_DELAY = 1.5
MAX_DELAY = 2.5
MAX_RETRIES = 3
RETRY_DELAY = 2

# --- Helper functions ---
async def fetch_html(session, url, semaphore, retries=MAX_RETRIES):
    async with semaphore:
        for attempt in range(1, retries + 1):
            try:
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                async with session.get(url, timeout=ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except Exception as e:
                if attempt < retries:
                    print(f"⚠️ Attempt {attempt} failed for {url}, retrying in {RETRY_DELAY}s...")
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    print(f"❌ Failed to fetch {url} after {retries} attempts: {e}")
                    return None

def save_links(file_path, links):
    with open(file_path, "a", encoding="utf-8") as f:
        for link in links:
            f.write(link + "\n")

def load_existing_links(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

# --- Scraping ---
async def process_episode(session, ep_url, existing_links, semaphore):
    html = await fetch_html(session, ep_url, semaphore)
    if not html:
        return []
    redirects = re.findall(r"/redirect/\d+", html)
    if not redirects:
        return []
    first_link = BASE_URL + redirects[0]
    if first_link not in existing_links:
        return [first_link]
    return []

async def process_season(session, season_link, existing_links, semaphore):
    full_season_url = BASE_URL + season_link
    print(f"\n➡️ Processing season -> {full_season_url}")
    season_html = await fetch_html(session, full_season_url, semaphore)
    if not season_html:
        return []

    episode_pattern = r'<a[^>]+href="(/serie/stream/[^"]*/staffel-\d+/episode-\d+)"'
    episodes = sorted(set(re.findall(episode_pattern, season_html)))

    if not episodes:
        print("No episodes found for this season.")
        return []

    tasks = [process_episode(session, BASE_URL + ep, existing_links, semaphore) for ep in episodes]
    results = []
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Episodes"):
        res = await f
        results.extend(res)
    return results

async def scrape_series():
    start_url = input("Enter the main series page URL: ").strip()
    base_name = input("Enter series name for folder: ").strip()

    # create folder for this series
    series_folder = os.path.join(TXT_FOLDER, base_name)
    os.makedirs(series_folder, exist_ok=True)

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        html = await fetch_html(session, start_url, semaphore)
        if not html:
            return None

        # find seasons
        season_pattern = r'<a[^>]+href="(/serie/stream/[^"]*/staffel-\d+)"'
        seasons = sorted(set(re.findall(season_pattern, html)))
        if not seasons:
            print("No seasons found.")
            return None

        print(f"📺 Found {len(seasons)} seasons:")
        for idx, slink in enumerate(seasons, 1):
            s_html = await fetch_html(session, BASE_URL + slink, semaphore)
            episodes = re.findall(r'<a[^>]+href="(/serie/stream/[^"]*/staffel-\d+/episode-\d+)"', s_html or "")
            print(f"  Season {idx}: {len(set(episodes))} episodes")

        # scrape each season
        for idx, season_link in enumerate(seasons, 1):
            output_file = os.path.join(series_folder, f"season{idx}.txt")
            existing_links = load_existing_links(output_file)
            redirects = await process_season(session, season_link, existing_links, semaphore)
            if redirects:
                save_links(output_file, redirects)
                print(f"✅ Saved {len(redirects)} links -> {output_file}")

    print("\n🎯 Finished scraping!")

# --- Download ---
def list_txt_files():
    files = []
    for root, _, filenames in os.walk(TXT_FOLDER):
        for f in filenames:
            if f.endswith(".txt"):
                files.append(os.path.join(root, f))
    if not files:
        print("⚠️ No txt files found.")
        return []
    print("\n📄 Saved txt files:")
    for idx, file in enumerate(files, 1):
        print(f"{idx}: {file}")
    return files

def download_txt_files():
    files = list_txt_files()
    if not files:
        return
    selection = input("Enter numbers (comma-separated) or 'all': ").strip()
    tmp_file = os.path.join(TXT_FOLDER, "tmp_download.txt")

    with open(tmp_file, "w", encoding="utf-8") as outfile:
        if selection.lower() == "all":
            for f in files:
                with open(f, "r", encoding="utf-8") as infile:
                    outfile.writelines(infile.readlines())
        else:
            indices = [int(x)-1 for x in selection.split(",") if x.isdigit() and 0 < int(x) <= len(files)]
            for i in indices:
                with open(files[i], "r", encoding="utf-8") as infile:
                    outfile.writelines(infile.readlines())

    print(f"\n▶️ Starting downloader with {tmp_file} ...")
    subprocess.run(["python", "dl.py", "-l", tmp_file, "-w", "1"])
    os.remove(tmp_file)

# --- Menu ---
def menu():
    os.makedirs(TXT_FOLDER, exist_ok=True)
    while True:
        print("\n=== Series Containern & Dumpster Driver ===")
        print("1: Dumpsterdive finest series out of thrash direct into your backpack")
        print("2: Upcycle found goodies")
        print("0: Exit")
        choice = input("Select option: ").strip()

        if choice == "1":
            asyncio.run(scrape_series())
        elif choice == "2":
            download_txt_files()
        elif choice == "0":
            break
        else:
            print("Invalid option!")

if __name__ == "__main__":
    menu()
