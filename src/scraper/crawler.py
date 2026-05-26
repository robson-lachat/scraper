# crawler.py
# RTX 5090 Crawler and Data Extractor
# This module is responsible for crawling
# the Digitec website to capture the latest
# HTML content of the search results for
# RTX 5090 products. It uses Playwright
# to ensure that dynamic content is fully
# loaded, and BeautifulSoup to parse the
# HTML and extract relevant information
# such as product name, price, availability,
# and URL. The extracted data is then
# processed with Mistral AI to structure
# it in a consistent format for further analysis.
# The workflow includes:
# 1. Capturing the search results page with Playwright.
# 2. Parsing the HTML with BeautifulSoup to find product articles.
# 3. Extracting product details using both rule-based methods and Mistral AI for structured output.
# 4. Generating a report of available products and their prices, highlighting the best deal.
# Note: Ensure that the MISTRAL_API_KEY is set in the .env file for AI processing.

import os
import re
import requests
import json
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from mistralai.client import Mistral
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from pydantic import BaseModel
from typing import Literal

# --- CONFIG ---
# Load .env
load_dotenv()
# Get API KEY
# api_key = os.getenv("GEMINI_API_KEY")
api_key = os.getenv("MISTRAL_API_KEY")
# Config Mistral
client = Mistral(api_key=api_key)
"mistral-tiny"  "open-mistral-7b"
model = "mistral-small-latest"

# Config Gemini
# client = genai.Client(api_key=api_key)
# model = "gemini-2.5-flash"


def get_html_with_request(url_target: str) -> str:
    response = requests.get(url_target)
    return response.text


# --- FUNCTION CAPTURE (CRAWLER) ---
def get_html_with_playright(p: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url_target)

        # Load page target
        # page.wait_for_load_state()
        page.wait_for_selector("article")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        page.wait_for_timeout(3000)

        html_content = page.content()
        browser.close()
    return html_content


# --- FUNCTION EXTRACT (PARSER) ---
def get_articles(html_contet: str) -> str:
    soup = BeautifulSoup(html_contet, "html.parser")
    articles = soup.find_all("article")
    print(f"Found {len(articles)}")
    return articles


def extract_article_data_with_bs(article) -> dict:
    try:
        text_full = article.get_text().lower()
        # Lógica simples de busca de palavras no texto do artigo
        # (Em francês, 'en stock' significa disponível)
        if "en stock" in text_full or "disponible" in text_full:
            availability_bs = "available"
        else:
            availability_bs = "unavailable"

        # 1. Try get name product
        link_tag = article.find("a", {"aria-label": True})
        name = link_tag["aria-label"] if link_tag else "Article not found"

        # 2. Find price block (class 'yRGTUHk')
        price_block = article.find("div", class_="yRGTUHk")
        if price_block:
            price_text = price_block.get_text().strip()
            # Clean price (ex: CHF 2999.– -> 2999)
            price_numeric = re.sub(r"[^\d]", "", price_text)
            price_val = int(price_numeric) if price_numeric else 0
        else:
            price_text = "Subject to consultation"
            price_val = 0

        # Filter to ensure it's an RTX 5090 and not a community post.
        if "5090" in name.upper() and price_val > 0:
            return {
                "product": name,
                "price_int": price_val,
                "availability": availability_bs
            }
    except Exception as e:
        # print(f"Erro ao processar um artigo: {e}")
        pass
    return None


def extract_article_data(url_target: str):
    html_content = get_html_with_playright(url_target)
    articles = get_articles(html_content)
    results = [extract_article_data_with_bs(article) for article in articles]
    return results


def extract_one_article_with_ll(article_obj) -> dict:
    link_tag = article_obj.find("a", href=True)
    full_url = f"https://www.digitec.ch{link_tag['href']}" if link_tag else "URL not found"
    # Transform HTML to text
    text = article_obj.get_text(separator=' ', strip=True)

    prompt = f"""
    Extract the following information in JSON format from the product text:
    - article_name: full name
    - price: the price number as a float
    - brand: manufacturer brand
    - availability: return ONLY "available" if the product is in stock/ready to ship, 
                    or "unavailable" if it is out of stock/sold out.

    If the product is not an RTX 5090 graphics card, return null.

    Text to analyze: {text}
    """

    try:
        chat_response = client.chat.complete(
            model=model,
            messages=[
                {"role": "user",
                 "content": prompt
                 },
            ],
            response_format={"type": "json_object"}
        )

        content = chat_response.choices[0].message.content
        data = json.loads(content)

        if data and data != "null":
            data['article_url'] = full_url

        return data

    except Exception as e:
        print(f"Error Mistral: {e}")
        return None


client_lc = ChatMistralAI(
    model=model,
    api_key=api_key,
    temperature=0,
    max_retries=2
)


# --- MODEL DATA (Exercice 1) ---
class DATArticle(BaseModel):
    article_name: str
    price: float
    brand: str
    article_url: str
    availability: Literal["available", "unavailable"]

# Function for extract in big strutured


def stract_one_article_data_with_structured_llm(article: str):
    prompt = f"""
    Given an article on an e-comerce website, in html format, as in the <ARTICLE> selection below.
    Your task is to extract the information into a json followin the format:
    {DATArticle.model_json_schema()}
    <ARTICLE>
    {article}
    </ARTICLE>
    """
    res = client_lc.with_structured_output(
        DATArticle, method="json_mode").invoke(prompt)
    return res.model_dump_json()


# --- FUNÇÕES DE ANÁLISE E RELATÓRIO ---
def run_ai_processing(articles: list, limit: int = None) -> list[dict]:
    """Loop de processamento dos artigos com IA."""
    results = []
    count = 0

    all_article = limit if limit else len(articles)

    print(f"\n--- Iniciando Extração com IA (Limite: {all_article}) ---")

    for art in articles:
        # Se houver um limite e ele for atingido, para.
        # Se limit for None, ele ignora esse 'if' e vai até o fim.
        if limit and count >= limit:
            break

        if "5090" in art.get_text():
            count += 1
            print(f"Analisando item {count}...")
            data = extract_one_article_with_ll(art)
            if data:
                results.append(data)

    return results


def generate_report(results: list[dict]):
    """Calcula o melhor preço e exibe o relatório final."""
    if not results:
        print("\n[!] Nenhum resultado válido encontrado para o relatório.")
        return

    print("\n" + "="*50)
    print("📋 RELATÓRIO DE PREÇOS RTX 5090")
    print("="*50)

    for res in results:
        status = "✅" if res['availability'] == "available" else "❌"
        print(f"{status} {res['article_name']} | CHF {res['price']}")

    # Cálculo de Melhor Preço (Apenas entre os disponíveis!)
    available_items = [r for r in results if r['availability'] == "available"]

    if available_items:
        best_deal = min(available_items, key=lambda x: x['price'])
        print("-" * 50)
        print(f"🔥 MELHOR OFERTA DISPONÍVEL: {best_deal['article_name']}")
        print(f"💰 Preço: CHF {best_deal['price']}")
        print(f"🔗 Link: {best_deal['article_url']}")
    else:
        print("\n⚠️ Nenhuma placa disponível em estoque no momento.")
    print("="*50)


if __name__ == "__main__":

    url_target = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"
    path_html = "tmp/5090_p.html"
    os.makedirs("tmp", exist_ok=True)

    # PARTE 1: Captura (Descomente para atualizar o arquivo local)
    # print("Executando Passo 1: Captura de HTML...")
    # html_raw = get_html_with_playright(url_target)
    # with open(path_html, "w", encoding="utf-8") as f:
    #     f.write(html_raw)

    # PARTE 2: Processamento e Relatório
    if os.path.exists(path_html):
        with open(path_html, "r", encoding="utf-8") as f:
            conteudo = f.read()

        # A) Busca os blocos de artigos
        lista_artigos = get_articles(conteudo)

        # B) Processa com IA (Pode comentar/uncomentar para testar)
        meus_resultados = run_ai_processing(lista_artigos, limit=None)

        # C) Gera Relatório (Sua nova função de cálculo!)
        generate_report(meus_resultados)

        # D) Salva em JSON para persistência
        with open("tmp/articles_mistral.json", "w", encoding="utf-8") as f:
            json.dump(meus_resultados, f, ensure_ascii=False, indent=2)

    else:
        print(f"Arquivo {path_html} não encontrado. Ative a PARTE 1.")
