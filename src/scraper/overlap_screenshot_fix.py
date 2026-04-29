import os
import base64
import json
from playwright.sync_api import sync_playwright
from mistralai.client import Mistral
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key)
model = "mistral-small-latest"


class RTXProduct(BaseModel):
    model_name: str = Field(description="Full product model name")
    price: float = Field(description="Numerical price value")

# --- CORE ---


def capture_overlapping_screenshots(url: str, output_dir: str):
    image_paths = []
    with sync_playwright() as p:
        # Usamos Chromium, mas definimos um User-Agent real para evitar o ERR_HTTP2
        # False para você ver acontecer
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_viewport_size({'width': 1280, 'height': 800})

        print(f"[*] Acessando: {url}")
        page.goto(url, wait_until="load")
        page.wait_for_timeout(2000)  # Espera carregar os preços

        step = 600
        for i in range(3):  # Captura 3 partes sobrepostas
            path = os.path.join(output_dir, f"overlap_{i}.png")
            page.screenshot(path=path)
            image_paths.append(path)

            page.mouse.wheel(0, step)
            page.wait_for_timeout(800)
            print(f"   [v] Screenshot {i} capturada.")

        browser.close()
    return image_paths


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
                    "text": "Liste as GPUs (modelo e preço) em JSON: {'products': []}"},
                {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"}
            ]
        }],
        response_format={"type": "json_object"}
    )

    data = json.loads(response.choices[0].message.content)
    return data.get("products", [])

# --- ORQUESTRAÇÃO ---


def run_exercise():
    base_dir = os.getcwd()
    output_dir = os.path.join(base_dir, "tmp", "screenshots")

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    url = "https://www.digitec.ch/fr/search?q=rtx5090"

    # 1. Captura (Estratégia de Sobreposição)
    imgs = capture_overlapping_screenshots(url, output_dir)

    # 2. Extração com IA
    all_extracted = []
    for img in imgs:
        print(f"[*] Analyzing: {img}")
        all_extracted.extend(analyze_image(img))

    # 3. DEDUPLICAÇÃO (A solução para os prints sobrepostos)
    # Se o nome for igual, o dicionário mantém apenas o último encontrado
    unique_data = {p['model_name']: p for p in all_extracted if 'model_name' in p}.values()

    print(
        f"\n[Results] Total extracted: {len(all_extracted)} | Unique products: {len(unique_data)}")
    print(json.dumps(list(unique_data), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run_exercise()
