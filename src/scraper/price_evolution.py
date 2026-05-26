# price_evolution.py
# Price Evolution Scraper and Analyzer
# This module captures price history data for RTX 5090
# products from Digitec, extracts relevant information
# using a structured approach, and analyzes trends with
# Mistral AI. The workflow includes:
# 1. Capturing the search results page with Playwright to ensure fresh data.
# 2. Parsing the HTML to extract product URLs.
# 3. For each product, using Playwright to interact with the price history chart and extract textual data.
# 4. Analyzing the extracted text with Mistral AI to identify current price, lowest/highest prices, and trend status.
# 5. Generating a final report in JSON format summarizing the price evolution for each product.
# Note: Ensure that the MISTRAL_API_KEY is set in the .env file for AI processing.

import os
import json
import base64
from typing import List, Literal, Optional
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --- LLM IMPORTS ---
from mistralai.client import Mistral
import google.generativeai as genai
from PIL import Image

# --- CONFIGURATION ---
load_dotenv()

# --- LOAD API KEYS ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- INITIALIZE MISTRAL ---
MISTRAL_CLIENT = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None
MISTRAL_MODEL = "mistral-small-latest"

# --- INITIALIZE GEMINI ---
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Note: Adjust the model name based on availability and requirements
    GEMINI_MODEL = "gemini-2.5-flash"
    # Global variable for control workflow
    ACTIVE_LLM = None  # Set to "mistral" or "gemini" based on which LLM you want to use


# API_KEY = os.getenv("MISTRAL_API_KEY")
# CLIENT = Mistral(api_key=API_KEY)
# AI_MODEL = "mistral-small-latest"

# --- DATA MODELS ---


class PriceTrendAnalysis(BaseModel):
    current_price: float = Field(
        description="The latest price shown today"
    )
    lowest_price_detected: float = Field(
        description="The lowest price in the historical period"
    )
    highest_price_detected: float = Field(
        description="The peak price in the historical period"
    )
    trend_status: Literal["increasing", "decreasing", "stable", "volatile"] = Field(
        description="The movement of the price in the recent period"
    )
    analysis_summary: str = Field(
        description="Brief explanation of the price movement"
    )
    recommendation: Literal["BUY", "WAIT", "DON'T BUY"] = Field(
        description="Final verdict: is it a good time to buy?"
    )


class ProductFilter(BaseModel):
    is_gpu: bool = Field(
        description="True if the product is an internal graphics card, False if it is an accessory, box, or cable.")
    product_name: str
    url: str

# --- CORE MODULES ---


def capture_main_search_page(url: str, output_path: str):
    """Captures the search page HTML ensuring fresh data."""
    print(f"[*] Capturing fresh search results from: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
                                    "--disable-http2", "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 ...")
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("article", timeout=20000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight/4)")
            page.wait_for_timeout(2000)
            html_content = page.content()
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"[+] Fresh HTML saved to {output_path}")
        except Exception as e:
            print(f"[!] Error capturing main page: {e}")
        finally:
            browser.close()


# This function uses the selected LLM to filter the list of candidates, keeping only those that are actual GPUs.
def filter_list_with_ai(candidates: List[dict]) -> List[dict]:
    if not candidates:
        return []

    print(
        f"[*] {ACTIVE_LLM.upper()} is is filtering {len(candidates)} candidates...")

    prompt = f"""
    Analyze this list of products from a hardware store. 
    Identify which ones are actual INTERNAL GRAPHICS CARDS (GPU) and which are accessories/boxes/eGPUs.
    Return a JSON list of objects with 'is_gpu' (boolean), 'product_name', and 'url'.
    
    Candidates: {json.dumps(candidates)}
    """

    if ACTIVE_LLM == "mistral":
        response = MISTRAL_CLIENT.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        data = json.loads(response.choices[0].message.content)

    if ACTIVE_LLM == "gemini":
        response = GEMINI_MODEL.generate_content(
            [prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0
            )
        )
        data = json.loads(response.text)

    # Adjust depending on how the AI structures the response, we get the list (adjust if necessary)
    results = data.get("products", data
                       ) if isinstance(data, dict) else data

    # Return only the items that the AI confirmed are GPUs
    filtered = [item for item in results if item.get("is_gpu") is True]
    print(f"[+] {ACTIVE_LLM.upper()} kept {len(filtered)} valid GPUs.")
    return filtered


def get_links_from_local_html(html_path: str, limit: int = 10) -> List[dict]:
    """Parses local HTML to extract product URLs and names."""
    if not os.path.exists(html_path):
        return []

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    products = []
    for art in soup.find_all("article"):
        name_tag = art.find("p", class_="yMYWssK1")
        link_tag = art.find("a", href=True)

        if name_tag and link_tag:
            product_name = name_tag.get_text(separator=" ", strip=True)
            href = link_tag['href']
            full_url = f"https://www.digitec.ch{href}" if href.startswith(
                "/") else href

            if "/product/" in full_url and "5090" in art.get_text():
                if full_url not in [p["url"] for p in products]:
                    products.append({
                        "url": full_url,
                        "product_name": product_name
                    })

        if len(products) >= limit:
            break

    return products


def fetch_trend_text_live(product_url: str) -> Optional[str]:
    print(f"[*] Analyzing details: {product_url}")

    # Recommended usage from playwright-stealth documentation
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # 1. Navigate to the product URL
            page.goto(product_url)

            # 2. Locate the button and scroll into view (replaces manual 4000px scroll)
            button = page.locator("#priceHistoryBlock")
            button.scroll_into_view_if_needed()

            # 3. Click to render the chart in the DOM
            print("    [+] Opening chart...")
            button.click()

            # Whait o gráfico aparecer
            svg = page.locator("svg.recharts-surface")
            svg.wait_for(state="visible")

            # Save print with ID do product to avoid overwriting
            product_id = product_url.split('/')[-1]
            screenshot_path = f"tmp/chart_{product_id}.png"
            svg.screenshot(path=screenshot_path)
            print(f"    [+] Screenshot saved to: {screenshot_path}")

            # 4. Wait for the chart selector to keep the script active until it appears
            page.wait_for_selector(
                "svg.recharts-surface", state="visible", timeout=3000)
            # Allow time for JS to render the numbers
            page.wait_for_timeout(2000)

            # Automate the screenshot taking of this graphic element
            # Ou o seletor pai do gráfico
            # chart_element = page.locator(".yAa8UXh")
            # chart_element.screenshot(
            #     path=f"screenshot_{product_url.split('/')[-1]}.png")

            # 5. Direct Extraction
            summary = ""
            summary_loc = page.locator("p.yAa8UXh").first
            if summary_loc.is_visible():
                summary = summary_loc.inner_text()

            # Capture chart labels from SVG
            labels = page.locator(
                "svg.recharts-surface text").all_inner_texts()
            chart_data = " | ".join([l.strip() for l in labels if l])

            print(f"    [v] Capture complete: {len(labels)} labels found.")
            # return f"Summary: {summary} \nData: {chart_data}"
            return {
                "text": f"Summary: {summary} \nData: {chart_data}",
                "screenshot": screenshot_path
            }

        except Exception as e:
            print(f"   [!] Capture error: {e}")
            return None
        finally:
            browser.close()


def analyze_trend_with_ai(text: str) -> dict:
    """Uses Mistral to extract numbers and trend, handling schema noise."""
    print(f"[*] {ACTIVE_LLM.upper()} analysis...")
    schema = PriceTrendAnalysis.model_json_schema()

    # Rigorous Prompt to avoid metadata
    prompt = f"""
    Analyze the price history text: "{text}"
    Return ONLY a flat JSON object with the data. 
    DO NOT include 'properties', 'required', or 'type' keys.
    Format: {json.dumps(schema, indent=2)}
    """

    if ACTIVE_LLM == "mistral":
        response = MISTRAL_CLIENT.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        raw_data = json.loads(response.choices[0].message.content)

    elif ACTIVE_LLM == "gemini":
        response = GEMINI_MODEL.generate_content(
            [prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0
            )
        )
        raw_data = json.loads(response.text)

    # Error handling: Remove the "properties" key if the AI includes it
    if "properties" in raw_data:
        raw_data = raw_data["properties"]

    return raw_data


# Utility function to encode images in base64 (if needed for AI input)
def encode_image(image_path: str) -> str:
    """Converte a imagem em base64 para envio à API."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


# Optional: Function to analyze the graph visually with Vision LLM (if supported by the model)
def analyze_graph_with_vision(image_path: str, product_name: str) -> dict:
    print(f"[*] {ACTIVE_LLM.upper()} Vision analysis for: {product_name}...")

    prompt = """
    Analyze this price history chart for a GPU.
    1. Look at the curve/line: is it generally going UP, DOWN, or is it FLAT?
    2. Identify the visual LOWEST and HIGHEST points if possible.
    3. Final Verdict: Based ONLY on the visual graph, is it a good time to buy?
    
    Return a JSON with: 'visual_trend', 'visual_min_price', 'visual_max_price', 'vision_recommendation'.
    """

    if ACTIVE_LLM == "mistral":
        base64_image = encode_image(image_path)
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{base64_image}"
                }
            ]
        }]
        response = MISTRAL_CLIENT.chat.complete(
            model=MISTRAL_MODEL,
            messages=messages,
            response_format="application/json",
            temperature=0
        )
        return json.loads(response.text)

    elif ACTIVE_LLM == "gemini":
        img = Image.open(image_path)
        response = GEMINI_MODEL.generate_content(
            [prompt, img],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0
            )
        )
        return json.loads(response.text)


# --- MAIN WORKFLOW ---
def run_price_evolution_workflow():

    # --- CONTROL PARAMETERS ---
    # How many items to fetch on the search page
    MAX_CANDIDATES = 10
    # How many of these to analyze deeply (the "live evolution")
    MAX_ANALYSIS = 3
    # ------------------------------

    search_url = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"
    base_dir = "tmp"
    os.makedirs(base_dir, exist_ok=True)

    path_html = os.path.join(base_dir, "search_result.html")
    path_list_json = os.path.join(base_dir, "product_list.json")
    path_evolution_json = os.path.join(base_dir, "price_evolution_final.json")

    # 1. HTML capture of search page
    capture_main_search_page(search_url, path_html)

    # 2. Extract and save the LIST of links (First JSON)
    candidates = get_links_from_local_html(path_html, limit=MAX_CANDIDATES)

    # Check if we have candidates to analyze
    if not candidates:
        print("[!] No URLs found.")
        return

    # 3. FILTRO COM IA (Aqui a IA decide quem é GPU real)
    # Passamos os nomes para a IA e ela nos devolve apenas os válidos
    valid_gpus = filter_list_with_ai(candidates)

    # Save the filtered list of valid GPUs (First JSON)
    with open(path_list_json, "w", encoding="utf-8") as f:
        json.dump(valid_gpus, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Product list saved to {path_list_json}")

    # 4. Análise profunda (Apenas nos que a IA confirmou)
    final_report = []

    # 3. Analyze each item
    for item in valid_gpus[:MAX_ANALYSIS]:
        url = item['url']
        # Returns dict with 'text' and 'screenshot'
        result = fetch_trend_text_live(url)

        if result:
            text_analysis = analyze_trend_with_ai(result['text'])
            # Show a snippet of the text extracted for debugging
            print(f"   [v] Text extracted: {result['text'][:100]}...")
        # Optional: Use Vision LLM to validate the trend visually (if supported by the model)
        vision_validation = analyze_graph_with_vision(
            result['screenshot'], item['product_name'])

        final_report.append({
            "product": item['product_name'],
            "text_data": text_analysis,
            "vision_validation": vision_validation,
            "screenshot_used": result['screenshot']
        })

        print(
            f"   [CHECK] Text Trend: {text_analysis.get('trend_status')} | Vision Trend: {vision_validation.get('visual_trend')}")

        history_text = fetch_trend_text_live(url)
        if history_text:
            try:
                # Call the AI with the cleaning treatment
                clean_data = analyze_trend_with_ai(history_text['text'])

                # Final validation with Pydantic
                validated = PriceTrendAnalysis(**clean_data)

                final_report.append({
                    "product": item['product_name'],
                    "url": url,
                    "analysis": validated.model_dump()
                })

                print(f"\n✅ Result for: {url.split('/')[-1]}")
                print(
                    f"   Trend: {validated.trend_status.upper()} | Now: {validated.current_price}")
            except Exception as e:
                print(f" [!] AI error during validation: {e}")

    # 4. Save Evolution Report (Second JSON)
    with open(path_evolution_json, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Evolution report saved to {path_evolution_json}")


# Optional: Function to select which LLM to use at runtime
def select_llm():
    """Show menu to choose the AI model."""
    global ACTIVE_LLM, GEMINI_MODEL

    print("\n" + "="*50)
    print("🤖 SELECT THE AI MODEL")
    print("="*50)
    print("1. Mistral AI")
    print("2. Google Gemini (2.5 Flash)")
    print("="*50)

    while True:
        choice = input("\nPlease enter 1 or 2 and press Enter: ").strip()

        if choice == "1":
            if not MISTRAL_API_KEY:
                print("[!] Error: MISTRAL_API_KEY not found in .env file!")
                continue
            ACTIVE_LLM = "mistral"
            print("\n[+] Mistral AI selected. Starting scraper...\n")
            break

        elif choice == "2":
            if not GEMINI_API_KEY:
                print("[!] Error: GEMINI_API_KEY not found in .env file!")
                continue
            ACTIVE_LLM = "gemini"
            GEMINI_MODEL = genai.GenerativeModel('gemini-1.5-flash')
            print("\n[+] Google Gemini selected. Starting scraper...\n")
            break

        else:
            print("[!] Invalid option. Please try again.")


if __name__ == "__main__":
    # 1. Select which LLM to use for the workflow
    select_llm()

    # 2. Run the main price evolution workflow
    run_price_evolution_workflow()
