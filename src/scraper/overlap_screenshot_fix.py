# oerlap_screenshot_fix.py
# This script captures multiple overlapping screenshots
# of a product listing page to ensure all products are visible,
# even if they overlap in the viewport.
# It then uses Mistral to extract product information from each
# screenshot and deduplicates the results based on the model name.
# The deduplication step is crucial to handle the overlap strategy,
# ensuring that we retain the most complete information for each product.
# The final output is a list of unique products with their model names and prices.
# The workflow includes:
# 1. Capturing multiple overlapping screenshots by scrolling the page.
# 2. Analyzing each screenshot with Mistral to extract product data.
# 3. Deduplicating the extracted products based on model names to ensure uniqueness.


import os
import base64
import json
from playwright.sync_api import sync_playwright
from mistralai.client import Mistral
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv

from scraper.image import save_analysis_to_json

# --- CONFIG ---
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key)
model = "mistral-small-latest"


class RTXProduct(BaseModel):
    model_name: str = Field(description="Full product model name")
    price: float = Field(description="Numerical price value")

# --- CORE ---


# Superposition strategy: Capture multiple screenshots with slight scrolls to ensure all
# products are captured, even if they overlap in the viewport.
# The deduplication step will handle any duplicates caused by the overlap.


def capture_overlapping_screenshots(url: str, output_dir: str):
    image_paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        view_width = 1000
        view_height = 900
        scroll_step = 500

        page.set_viewport_size({'width': view_width, 'height': view_height})

        try:
            print(f"[*] Accessing: {url}")

            page.goto(url, wait_until="load")
            page.wait_for_timeout(2000)

            total_height = page.evaluate("document.body.scrollHeight")
            current_scroll = 0
            total_steps = 4
            i = 0

            while current_scroll < total_height and i < total_steps:

                path = os.path.join(output_dir, f"overlap_{i}.png")
                page.screenshot(path=path)
                image_paths.append(path)

                print(
                    f"   [v] Captured screenshot {i} at scroll position {current_scroll} {current_scroll + view_height}.")

                current_scroll += scroll_step
                page.mouse.wheel(0, scroll_step)

                page.wait_for_timeout(800)
                i += 1

        except Exception as e:
            print(f"[!] Error during screenshot capture: {e}")

        finally:
            browser.close()

    return image_paths


# Extract information from each screenshot using Mistral,
# asking for a JSON with model names and prices.
# The deduplication will be done later based on the model name.


def analyze_image(image_path: str) -> List[dict]:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')

    response = client.chat.complete(
        model=model,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",
                    "text": """List the visible GPUs. Return ONLY a JSON in the format:
                            {'products': [{'model_name': 'full name', 'price': 0.0}]}.
                            If there are no visible products, return {'products': []}."""},
                {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"}
            ]
        }],
        response_format={"type": "json_object"}
    )

    data = json.loads(response.choices[0].message.content)
    return data.get("products", [])

# --- MAIN WORKFLOW ---


def run_exercise():
    base_dir = os.getcwd()
    output_dir = os.path.join(base_dir, "tmp", "screenshots")

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    url = "https://www.digitec.ch/fr/search?q=rtx5090"

    # 1. Capture overlapping screenshots
    imgs = capture_overlapping_screenshots(url, output_dir)

    # 2. Extract information from each screenshot
    all_extracted = []
    for img in imgs:
        print(f"[*] Analyzing: {img}")
        data = analyze_image(img)
        all_extracted.extend(data)

    # 3. DEDUPLICATION products by model name (keep the last occurrence, which is likely the most complete due to the overlap strategy)
    unique_products = {}
    for p in all_extracted:

        name = p.get('model_name') or p.get('model') or p.get('product')
        if name:
            unique_products[name] = p

    final_data = list(unique_products.values())

    print(
        f"\n[Results] Total extracted: {len(all_extracted)} | Unique products: {len(final_data)}")
    print(json.dumps(final_data, indent=2, ensure_ascii=False))

    # Optionally save to JSON
    save_analysis_to_json({"products": final_data}, os.path.join(
        base_dir, "tmp", "final_products.json"))


if __name__ == "__main__":
    run_exercise()
