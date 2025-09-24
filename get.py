import re
import os
import asyncio
import aiohttp
import random
import subprocess
import json
from aiohttp import ClientTimeout
from tqdm import tqdm

BASE_URL = "https://s.to"
TXT_FOLDER = "txt"
CONCURRENT_REQUESTS = 5
MIN_DELAY = 1.5
MAX_DELAY = 2.5
MAX_RETRIES = 3
RETRY_DELAY = 2
STATE_FILE = "state.json"

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

def save_state(start_url, base_name):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"url": start_url, "name": base_name}, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# --- Scraping ---
async def process_episode(session, ep_url, existing_links, semaphore):
    html = await fetch_html(session, ep_url, semaphore)
    if not html:
        return []
    redirects = re.findall(r"/redirect/\d+", html)
    return [BASE_URL + r for r in sorted(set(redirects)) if BASE_URL + r not in existing_links]

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

async def scrape_series(resume=False):
    if resume:
        state = load_state()
        if not state:
            print("⚠️ No saved state found.")
            return None
        start_url = state["url"]
        base_name = state["name"]
        print(f"▶️ Resuming: {base_name} ({start_url})")
    else:
        start_url = input("Enter the main series page URL: ").strip()
        base_name = input("Enter series name for txt files: ").strip()
        save_state(start_url, base_name)

    os.makedirs(TXT_FOLDER, exist_ok=True)

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        html = await fetch_html(session, start_url, semaphore)
        if not html:
            return None

        # preview
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

        confirm = input("Proceed with scraping? (y/n): ").strip().lower()
        if confirm != "y":
            print("❌ Cancelled.")
            return None

        # scrape each season separately into its own file
        for idx, season_link in enumerate(seasons, 1):
            output_file = os.path.join(TXT_FOLDER, f"{base_name}_season{idx}.txt")
            existing_links = load_existing_links(output_file)
            redirects = await process_season(session, season_link, existing_links, semaphore)
            if redirects:
                save_links(output_file, redirects)
                print(f"✅ Saved {len(redirects)} links -> {output_file}")

    print("\n🎯 Finished scraping!")

# --- Download ---
def list_txt_files():
    files = sorted([f for f in os.listdir(TXT_FOLDER) if f.endswith(".txt")])
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
                with open(os.path.join(TXT_FOLDER, f), "r", encoding="utf-8") as infile:
                    outfile.writelines(infile.readlines())
        else:
            indices = [int(x)-1 for x in selection.split(",") if x.isdigit() and 0 < int(x) <= len(files)]
            for i in indices:
                with open(os.path.join(TXT_FOLDER, files[i]), "r", encoding="utf-8") as infile:
                    outfile.writelines(infile.readlines())

    print(f"\n▶️ Starting downloader with {tmp_file} ...")
    subprocess.run(["python", "dl.py", "-l", tmp_file, "-w", "1"])
    os.remove(tmp_file)

# --- Menu ---
def menu():
    os.makedirs(TXT_FOLDER, exist_ok=True)
    while True:
        print("\n=== Series Scraper & Downloader ===")
        print("1: Scrape series into txt file")
        print("2: Download from saved txt files")
        print("3: Resume last scrape")
        print("0: Exit")
        choice = input("Select option: ").strip()

        if choice == "1":
            asyncio.run(scrape_series())
        elif choice == "2":
            download_txt_files()
        elif choice == "3":
            asyncio.run(scrape_series(resume=True))
        elif choice == "0":
            break
        else:
            print("Invalid option!")

if __name__ == "__main__":
    menu()
