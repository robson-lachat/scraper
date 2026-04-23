import os
import base64
import json
from playwright.sync_api import sync_playwright
from mistralai.client import Mistral
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from typing import List, Literal

# --- CONFIG ---
# Load .env
load_dotenv()
# Get API KEY
api_key = os.getenv("MISTRAL_API_KEY")
# Config Mistral
client = Mistral(api_key=api_key)
# "mistral-tiny"  "open-mistral-7b"
model = "mistral-small-latest"


# --- DATA MODELS (Pydantic) ---
class RTXProduct(BaseModel):
    manufacturer: str = Field(
        description="GPU manufacturer (e.g., ASUS, MSI, Gigabyte, Zotac)")
    model_name: str = Field(description="Full product model name")
    price_chf: float = Field(description="Numerical price value in CHF")
    availability: Literal["available", "unavailable"] = Field(
        description="Stock status on the website")


class RTXList(BaseModel):
    """Wrapper for the list of products to enforce structured output"""
    products: List[RTXProduct]

# --- CORE MODULES ---


def capture_full_page_screenshot(url: str, output_path: str):
    """
    Handles Playwright browser instance to capture a full-page image.
    Includes scrolling logic to trigger lazy-loading of product images.
    """
    print(f"[*] Starting browser to capture: {url}")

    with sync_playwright() as p:
        # Launching in headless mode for server environments
        # Added User-Agent to prevent protocol errors and bot detection blocks
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()

        try:
            # Navigate and wait for the initial load
            page.goto(url, wait_until="load", timeout=60000)

            # Trigger lazy load: scroll to the bottom of the page
            print("[*] Scrolling to load all dynamic content...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(4000)  # Wait for images to render

            # Capture the entire document length
            page.screenshot(path=output_path, full_page=True)
            print(f"[+] Full-page screenshot saved: {output_path}")

        except Exception as e:
            print(f"[!] Error during capture: {e}")
            raise e
        finally:
            browser.close()


def encode_image_to_base64(image_path: str) -> str:
    """Converts local image file to base64 string for API transmission"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def analyze_vision_data(base64_image: str) -> dict:
    """
    Sends the screenshot to Mistral AI for visual analysis.
    Requesting structured JSON output based on the Pydantic schema.
    """
    print(f"[*] Analyzing image with AI Model: {model}")

    # Get JSON schema from Pydantic model for the prompt
    schema_definition = RTXList.model_json_schema()

    prompt = f"""
    Extract all RTX 5090 graphics cards from this Digitec store screenshot.
    Return the data strictly in JSON format matching this schema:
    {json.dumps(schema_definition, indent=2)}
    
    Ensure price_chf is a clean float and availability is based on the stock tags.
    """

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": f"data:image/png;base64,{base64_image}"}
            ]
        }
    ]

    response = client.chat.complete(
        model=model,
        messages=messages,
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def save_analysis_to_json(data: dict, file_path: str):
    """Persists extracted data into a JSON file for future use"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[+] Structured data saved to: {file_path}")

# --- MAIN ORCHESTRATOR ---


def run_visual_analysis_workflow():
    """Main function that coordinates the execution of all steps"""

    # Path settings
    base_dir = "/home/ia-user/Documents/scraper/tmp"
    os.makedirs(base_dir, exist_ok=True)

    screenshot_file = os.path.join(base_dir, "digitec_rtx5090_full.png")
    json_result_file = os.path.join(base_dir, "image_vision_results.json")
    target_url = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"

    # Step 1: Capture Page
    capture_full_page_screenshot(target_url, screenshot_file)

    # Step 2: Prepare Image
    base64_data = encode_image_to_base64(screenshot_file)

    # Step 3: AI Vision Extraction
    try:
        final_data = analyze_vision_data(base64_data)

        # Step 4: Save and Print Summary
        save_analysis_to_json(final_data, json_result_file)

        print("\n--- EXTRACTION SUMMARY ---")
        for item in final_data.get("products", []):
            stock_icon = "🟢" if item['availability'] == "available" else "🔴"
            print(
                f"{stock_icon} {item['manufacturer']} | {item['model_name']} | CHF {item['price_chf']}")

    except Exception as e:
        print(f"[!] Error during AI processing: {e}")


if __name__ == "__main__":
    # capture_and_analyze()
    run_visual_analysis_workflow()
