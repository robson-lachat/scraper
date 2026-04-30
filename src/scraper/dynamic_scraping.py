import os
import json
from os import path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from pydantic import main
from scrapegraphai.graphs import SmartScraperGraph


# --- CONFIG ---
OUTPUT_DIR = os.path.join(os.getcwd(), "tmp", "dnc_scpg")

# --- OLLAMA CONFIG ---
graph_config = {
    "llm": {
        "model": "ollama/phi3",
        "temperature": 0,
        "format": "json",
        "base_url": "http://localhost:11434",
        "model_tokens": 8192,
    },
    "embeddings": {
        "model": "ollama/nomic-embed-text",
        "base_url": "http://localhost:11434",
    },
    "verbose": True,
}

# --- FUNCTION CAPTURE (CRAWLER) ---


def get_html_content(url: str) -> str:
    print(f"[!] Capturing content from: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        page = context.new_page()
        Stealth.apply_sync(page)

        page.goto(url)

        # Load page target
        page.wait_for_load_state("networkidle")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        page.wait_for_timeout(3000)

        html_content = page.content()
        browser.close()
    return html_content


# --- FUNCTION EXTRACT (PARSER) ---
def get_articles(html_contet: str) -> str:
    soup = BeautifulSoup(html_contet, "html.parser")

    return soup


def save_files_directory(base_dir):
    base_dir = os.getcwd()
    output_dir = os.path.join(base_dir, "tmp", "dnc_scpg")

    save_html(base_dir, "tmp", "site.html")


# MAIN WORKFLOW


def main():
    target_site = [
        "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"
        # "other sites to scrape",
    ]

    while len(target_site) > 0:
        try:
            html = get_html_content(target_site[0])

            # --- SAVE FILES ---
            save_raw_html(html, f"site_{i}.html")

            soup = parse_basic_info(html)
            print(f"[!] Title WEB page: {soup.title.string}")

        except Exception as e:
            print(f"Error processing {target_site[0]}: {e}")


if __name__ == "__main__":
    main()
