import os
import json
from os import path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from pydantic import main
from scrapegraphai.graphs import SmartScraperGraph
from undetected_playwright import stealth_sync


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
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

        page = context.new_page()
        stealth_sync(page)

        page.goto(url)

        # Load page target
        page.wait_for_load_state()
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        page.wait_for_timeout(3000)

        html_content = page.content()
        browser.close()
    return html_content


# --- MÓDULO DE ARQUIVOS ---
def save_raw_html(html_data: str, filename: str):
    """Garante que o diretório existe e salva o HTML bruto."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[+] Diretório criado: {OUTPUT_DIR}")

    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_data)
    print(f"[OK] Arquivo salvo em: {file_path}")


# --- MÓDULO DE PROCESSAMENTO (PARSER) ---
def parse_basic_info(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    # Aqui você poderia extrair títulos, preços, etc.
    # Por enquanto, apenas retornamos o soup como solicitado
    return soup


# --- MAIN WORKFLOW ---
def main():
    target_site = [
        "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106",
        "https://www.interdiscount.ch/fr/search?search=rtx5090&category=Carte%2520graphique",
        "https://www.fr.fnac.ch/SearchResult/ResultList.aspx?SCat=8!1%2c8006!2&SDM=list&Search=rtx5090&sft=1"
    ]

    i = 0
    while i < len(target_site):
        try:
            html = get_html_content(target_site[i])

            # --- SAVE FILES ---
            save_raw_html(html, f"site_{i}.html")

            soup = parse_basic_info(html)
            print(f"[!] Title WEB page: {soup.title.string}")

        except Exception as e:
            print(f"Error processing {target_site[i]}: {e}")
        i += 1


if __name__ == "__main__":
    main()
