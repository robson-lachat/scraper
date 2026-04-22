# crawler.py
import os
import re
import requests
import json
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from mistralai.client import Mistral
# from mistralai import Mistral
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI


# Load .env
load_dotenv()

# Get API KEY
api_key = os.getenv("MISTRAL_API_KEY")

# Config Mistral
client = Mistral(api_key=api_key)
# "mistral-tiny"  "open-mistral-7b"
model = "mistral-small-latest"


def get_html_with_request(url:str) -> str:
    response = requests.get(url)
    return response.text

def get_html_with_playright(url:str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url)
        # page.wait_for_load_state()
        page.wait_for_timeout(2000)
        html_content = page.content()
        browser.close()
    return html_content


def get_articles(html_contet:str) -> str:
    soup = BeautifulSoup(html_contet, "html.parser")
    articles = soup.find_all("article")
    print(f"Found {len(articles)}")
    return articles

def extract_article_data_with_bs(article) -> dict:
    try:
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
                "price_str": price_text,
                "price_int": price_val
            }
    except Exception as e:
        # print(f"Erro ao processar um artigo: {e}")
        pass
    return None


# def extract_article_data(url:str):
#     html = get_html_with_playright(url)
#     articles = get_articles(html_content)
#     results = [extract_article_data_with_bs(article) fro article in articles]
#     return

def extract_one_article_with_ll(article_obj) -> dict:
    """
    Use Mistral AI for extract data in HTML.
    """
    # Transform HTML to text
    text = article_obj.get_text(separator=' ', strip=True)

    prompt = f"""
    From the following product text, extract the information in JSON:
    - product: full name
    - price_int: only the price number (integer)
    - brand: the manufacturer's brand

    If the product is not an RTX 5090 graphics card, return null.

    Text: {text}
    """

    try:
        chat_response = client.chat.complete(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"} 
        )
        
        content = chat_response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"Error Mistral: {e}")
        return None


client_lc = ChatMistralAI(
    model=model,
    api_key=api_key,
    temperature=0,
    max_retries=2
    )
from pydantic import BaseModel, Field

class DATArticle(BaseModel):
    article_name: str
    price: float
    article_url: str

# Function for extract in big strutured
def stract_one_article_data_with_structured_llm(article: str):
    prompt= f"""
    Given an article on an e-comerce website, in html forma, as in the <ARTICLE> selection below.
    Your task is to extract the information into a json followin the format:
    {DATArticle.model_json_schema()}
    <ARTICLE>
    {article}
    </ARTICLE>
    """
    res = client_lc.with_structured_output(DATArticle, method="json_mode").invoke(prompt)
    return res.model_dump_json()

if __name__ == "__main__":
    
    # url = "https://www.digitec.ch/fr/search?q=rtx5090&filter=pt%3D106"

    file_path = "tmp/5090_p.html"
    
    # html_content = get_html_with_request(eurl)
    # html_content = get_html_with_playright(url)
    # html_content = get_html_with_playright(url)
    # with open("tmp/5090_p.html", "w") as file:
    #     file.write(html_content)

    # if os.path.exists(file_path):
    #     with open(file_path, "r", encoding="utf-8") as f:
    #         html_content = f.read()
            
    #     articles = get_articles(html_content)
    #     results = []
        
    #     for art in articles:
    #         data = extract_article_data_with_bs(art)
    #         if data:
    #             results.append(data)
        
    #     # Order by minor price
    #     results = sorted(results, key=lambda x: x["price_int"])
        
    #     # Save JSON file
    #     os.makedirs("tmp", exist_ok=True)
    #     with open("tmp/articles.json", "w", encoding="utf-8") as file:
    #         json.dump(results, file, ensure_ascii=False, indent=2)
            
    #     print(f"\nExtract finish {len(results)} real offert faund.")
    #     for res in results:
    #         print(f"Price: {res['price_str']} | Product: {res['product']}")
    # else:
    #     print(f"File {file_path} not found. Run Playwright frist.")

    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        articles = get_articles(html_content)
        results = []
        
        print(f"\n--- Starting Mistral AI Extraction ---")
        
        # Limitamos a 3 para teste inicial e economia de tokens
        count = 0
        for art in articles:
            # Filtro básico antes de mandar para a IA economiza processamento
            if "5090" in art.get_text() and count < 3:
                print(f"Analyzing item {count + 1} with IA...")
                data = extract_one_article_with_ll(art)
                
                # Se a IA retornar o objeto (e não null), adicionamos
                if data and data != "null":
                    results.append(data)
                    count += 1

        # Salva o resultado final em JSON
        os.makedirs("tmp", exist_ok=True)
        output_file = "tmp/articles_mistral.json"
        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(results, file, ensure_ascii=False, indent=2)
            
        print(f"\nFinish! Check the results in: {output_file}")
        
        # Exibe o melhor preço encontrado pela IA
        if results:
            best_deal = min(results, key=lambda x: x['price_int'])
            print(f"Best Deal found by AI: {best_deal['product']} - CHF {best_deal['price_int']}")
    else:
        print(f"File {file_path} not found. Run Playwright first.")