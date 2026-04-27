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
        description="GPU manufacturer")
    model_name: str = Field(description="Full product model name")
    price: float = Field(description="Numerical price value")
    availability: Literal["available", "unavailable"] = Field(
        description="Stock status on the website")


class RTXList(BaseModel):
    """Wrapper for the list of products to enforce structured output"""
    products: List[RTXProduct]

# --- CORE MODULES ---


def capture_product_chunks(target_url: str, output_dir: str, limit: int = 10) -> List[str]:
    """
    Finds all product containers and takes individual screenshots of each.
    This avoids resolution issues and memory limits.
    """
    image_paths = []
    print(f"[*] Navigating to: {target_url}")

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
            page.goto(target_url, wait_until="load", timeout=60000)

            # Navigate and wait for the initial load
            print("[*] Waiting for product elements (article)...")
            page.wait_for_selector("article", timeout=30000)

            # Find all product elements
            product_elements = page.locator("article")
            total_count = product_elements.count()
            count = min(total_count, limit)

            print(

                f"[+] Found {total_count} items. Capturing first {count} chunks...")

            for i in range(count):
                element = product_elements.nth(i)
                # Scroll to element so it's fully visible and loaded
                element.scroll_into_view_if_needed()
                # Wait a bit for images to be crisp
                page.wait_for_timeout(1000)

                chunk_path = os.path.join(output_dir, f"chunk_prod_{i}.png")
                element.screenshot(path=chunk_path)
                image_paths.append(chunk_path)
                print(f"   [v] Screenshot taken for item {i}")

        except Exception as e:
            print(f"[!] Error during capture: {e}")
            raise e

        finally:
            browser.close()

    return image_paths

# ... (The rest of the functions encode_image, analyze_single_chunk, save_analysis_to_json stay the same)


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


def analyze_single_chunk(base64_image: str) -> dict:
    """
    Analyzes a product image and strictly enforces the Pydantic model.
    """
    prompt = f"""
    The given image is the screenshot of a GPU article on a e-commerce website.
    Extract the information on the article.
    
    Return the result in json format. 
    Target Schema: {RTXProduct.model_json_schema()}   """

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
        response_format={"type": "json_object"},
        temperature=0
    )

    # 1. Parse the raw string into a dict
    raw_data = json.loads(response.choices[0].message.content)

    # 2. FIX: Check if the AI wrapped the data inside 'properties'
    if "properties" in raw_data:
        raw_data = raw_data["properties"]

    # 3. ENFORCE: Use Pydantic to validate and clean the data
    try:
        # This is where the BaseModel actually takes control
        validated_product = RTXProduct(**raw_data)
        return validated_product.model_dump()
    except Exception as e:
        print(f" [!] Validation error, attempting fallback: {e}")
        # Fallback logic or return a default/None
        return raw_data


def save_analysis_to_json(data: dict, file_path: str):
    """Persists extracted data into a JSON file for future use"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[+] Structured data saved to: {file_path}")

# --- MAIN ORCHESTRATOR ---


def run_visual_analysis_workflow():
    project_root = os.getcwd()
    base_dir = os.path.join(project_root, "tmp")
    chunks_dir = os.path.join(base_dir, "chunks")

    os.makedirs(chunks_dir, exist_ok=True)

    target_url = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"
    final_results = []

    # Step 1: Capture individual chunks (High Resolution)
    chunk_files = capture_product_chunks(target_url, chunks_dir, limit=5)

    # Step 2 & 3: Encode and Analyze each chunk separately
    print(f"[*] Starting AI analysis on {len(chunk_files)} images...")
    for img_path in chunk_files:
        try:
            b64 = encode_image(img_path)
            product_data = analyze_single_chunk(b64)
            final_results.append(product_data)
            print(
                f"   [+] Processed: {product_data.get('model_name', 'Unknown')}")
        except Exception as e:
            print(f"   [!] Error analyzing {img_path}: {e}")

    # Step 4: Save consolidated JSON
    json_result_file = os.path.join(base_dir, "image_vision_results_v2.json")
    consolidated_data = {"products": final_results}

    with open(json_result_file, "w", encoding="utf-8") as f:
        json.dump(consolidated_data, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Structured data saved to: {json_result_file}")


if __name__ == "__main__":
    run_visual_analysis_workflow()
