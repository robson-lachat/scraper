import os
import json
import re
from typing import List, Literal, Optional
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from mistralai.client import Mistral
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("MISTRAL_API_KEY")
CLIENT = Mistral(api_key=API_KEY)
AI_MODEL = "mistral-small-latest"

# --- DATA MODELS ---


class PriceTrendAnalysis(BaseModel):
    current_price: float = Field(description="The latest price shown today")
    lowest_price_detected: float = Field(
        description="The lowest price in the historical period")
    highest_price_detected: float = Field(
        description="The peak price in the historical period")
    trend_status: Literal["increasing", "decreasing", "stable", "volatile"] = Field(
        description="The movement of the price in the recent period"
    )
    analysis_summary: str = Field(
        description="Brief explanation of the price movement")

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


def get_links_from_local_html(html_path: str, limit: int = 5) -> List[str]:
    """Parses local HTML to extract product URLs."""
    if not os.path.exists(html_path):
        return []
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    links = []
    for art in soup.find_all("article"):
        link_tag = art.find("a", href=True)
        if link_tag:
            href = link_tag['href']
            full_url = f"https://www.digitec.ch{href}" if href.startswith(
                "/") else href
            if "/product/" in full_url and "5090" in art.get_text():
                if full_url not in links:
                    links.append(full_url)
        if len(links) >= limit:
            break
    return links


def fetch_trend_text_live(product_url: str) -> Optional[str]:
    print(f"[*] Analisando detalhes: {product_url}")
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            page.goto(product_url)

            # Scroll para garantir que o botão seja carregado
            page.evaluate("window.scrollTo(0, 4000)")

            selector_btn = "#priceHistoryBlock"
            page.wait_for_selector(
                selector_btn, state="attached", timeout=15000)
            button = page.locator(selector_btn)

            # Verificamos se precisa clicar
            expanded = button.get_attribute("aria-expanded")
            if expanded == "false" or expanded is None:
                print("    [+] Abrindo gráfico via JS Dispatch...")
                # Usamos dispatch_event para simular um clique real no nível do motor do navegador
                button.dispatch_event("click")

            # --- ESPERA PELO SVG ---
            print("    [*] Aguardando gráfico aparecer...")
            try:
                # Aumentamos para 15s porque o gráfico do Digitec é lento
                page.wait_for_selector(
                    "svg.recharts-surface", state="visible", timeout=15000)
                # Tempo para os números serem desenhados
                page.wait_for_timeout(2000)
            except:
                print("    [!] O gráfico não apareceu. Tirando print de erro...")
                page.screenshot(path="erro_grafico.png")
                return None

            # --- EXTRAÇÃO SEGURA ---
            summary_text = ""
            summary_loc = page.locator("p.yAa8UXh").first
            if summary_loc.is_visible():
                summary_text = summary_loc.inner_text()

            # Captura labels evitando o erro de NoneType
            labels_raw = page.locator(
                "svg.recharts-surface text").all_inner_texts()

            # Filtro ultra-seguro para evitar o erro 'NoneType'
            clean_labels = []
            for l in labels_raw:
                if l is not None:
                    txt = str(l).strip()
                    if txt:
                        clean_labels.append(txt)

            chart_data = " | ".join(clean_labels)
            print(
                f"    [v] Captura concluída. Labels encontrados: {len(clean_labels)}")

            return f"Resumo: {summary_text} \nDados do Gráfico: {chart_data}"

        except Exception as e:
            print(f"   [!] Erro durante a execução: {e}")
            return None
        finally:
            page.close()
            browser.close()


def analyze_trend_with_ai(text: str) -> dict:
    """Uses Mistral to extract numbers and trend, handling schema noise."""
    print("[*] Mistral analysis...")
    schema = PriceTrendAnalysis.model_json_schema()

    # Prompt mais rigoroso para evitar metadados
    prompt = f"""
    Analyze the price history text: "{text}"
    Return ONLY a flat JSON object with the data. 
    DO NOT include 'properties', 'required', or 'type' keys.
    Format: {json.dumps(schema, indent=2)}
    """

    response = CLIENT.chat.complete(
        model=AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0
    )

    raw_data = json.loads(response.choices[0].message.content)

    # TRATAMENTO DE ERRO: Remove o "properties" se a IA teimar em incluir
    if "properties" in raw_data:
        raw_data = raw_data["properties"]

    return raw_data

# --- MAIN WORKFLOW ---


def run_price_evolution_workflow():
    search_url = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"
    base_dir = "tmp"
    os.makedirs(base_dir, exist_ok=True)

    path_html = os.path.join(base_dir, "5090_p.html")
    path_list_json = os.path.join(base_dir, "product_list.json")
    path_evolution_json = os.path.join(base_dir, "price_evolution_final.json")

    # 1. Capturar HTML da busca
    capture_main_search_page(search_url, path_html)

    # 2. Extrair e salvar a LISTA de links (Primeiro JSON)
    urls = get_links_from_local_html(path_html, limit=2)
    with open(path_list_json, "w", encoding="utf-8") as f:
        json.dump({"captured_urls": urls}, f, indent=2)
    print(f"[+] Product list saved to {path_list_json}")

    if not urls:
        print("[!] No URLs found.")
        return

    final_report = []

    # 3. Analisar cada item
    for url in urls:
        history_text = fetch_trend_text_live(url)
        if history_text:
            try:
                # Chama a IA com o tratamento de limpeza
                clean_data = analyze_trend_with_ai(history_text)

                # Validação final com Pydantic
                validated = PriceTrendAnalysis(**clean_data)

                final_report.append({
                    "url": url,
                    "analysis": validated.model_dump()
                })

                print(f"\n✅ Result for: {url.split('/')[-1]}")
                print(
                    f"   Trend: {validated.trend_status.upper()} | Now: {validated.current_price}")
            except Exception as e:
                print(f" [!] AI error during validation: {e}")

    # 4. Salvar Relatório de Evolução (Segundo JSON)
    with open(path_evolution_json, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Evolution report saved to {path_evolution_json}")


if __name__ == "__main__":
    run_price_evolution_workflow()
