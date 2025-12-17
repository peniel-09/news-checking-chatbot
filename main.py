import os
from fastapi import FastAPI, Request
from apify_client import ApifyClient
from openai import OpenAI
import httpx

app = FastAPI()

# Clés
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
apify_client = ApifyClient(APIFY_TOKEN)

# Liste des pages à surveiller (URLs Facebook)
OFFICIAL_PAGES = [
    "https://www.facebook.com/asinbenin",
    "https://www.facebook.com/gouvbenin"
]

@app.post("/webhook")
async def receive_whatsapp(request: Request):
    data = await request.json()
    # ... (Extraction du message utilisateur comme avant) ...
    try:
        entry = data['entry'][0]['changes'][0]['value']
        message_body = entry['messages'][0]['text']['body']
        sender_id = entry['messages'][0]['from']
    except:
        return {"status": "ignored"}

    # Récupérer les derniers posts via Apify ---
    # Scraper les 5 derniers posts de chaque page
    run_input = {
        "startUrls": [{"url": url} for url in OFFICIAL_PAGES],
        "resultsLimit": 5, 
    }

    # On lance le scraper
    run = apify_client.actor("apify/facebook-posts-scraper").call(run_input=run_input)

    # On récupère les résultats
    dataset_items = apify_client.dataset(run["defaultDatasetId"]).list_items().items
    
    # --- Préparation du contexte pour GPT ---
    # On va construire un contexte qui inclut le TEXTE des posts et les IMAGES
    gpt_content_context = []
    
    for item in dataset_items:
        # Texte du post
        text = item.get("text", "Pas de texte")
        # URL du post (pour la source)
        post_url = item.get("url", "")
        # Image du post (crucial pour les communiqués officiels format image)
        image_url = item.get("images", [None])[0] 

        gpt_content_context.append({
            "text": text,
            "url": post_url,
            "image": image_url
        })

    # --- Prompt Système ---
    system_prompt = """
    Tu es un Fact-Checker pour le Bénin. Analyse la rumeur de l'utilisateur en la comparant 
    aux DERNIERS POSTS OFFICIELS ci-dessous.
    
    Attention : Les informations officielles peuvent se trouver dans le texte OU dans les images (communiqués).
    
    Si un post récent dément ou confirme la rumeur :
    1. Dis-le clairement.
    2. Donne le lien Facebook du post officiel.
    
    Si aucun des posts récents ne parle de ça, dis : 
    "Je n'ai rien trouvé dans les dernières annonces officielles (Facebook ASIN/Gouv). La rumeur est peut-être trop ancienne ou non traitée."
    """

    # Préparation du message pour GPT (Texte + Description des posts)
 
    
    context_str = ""
    for item in gpt_content_context:
        context_str += f"\n--- POST FACEBOOK ---\nSource: {item['url']}\nContenu: {item['text']}\n"
        if item['image']:
             context_str += f"[Il y a une image associée : {item['image']}]\n"

    completion = openai_client.chat.completions.create(
        model="gpt-4o", # On utilise le modèle puissant pour bien comprendre
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Rumeur à vérifier : {message_body}\n\nContexte Officiel Récent :{context_str}"}
        ]
    )
    
    bot_response = completion.choices[0].message.content

    # ......