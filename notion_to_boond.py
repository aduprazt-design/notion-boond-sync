"""
Script Notion -> Boond : synchronisation des transcriptions d'entretiens
Variables d'environnement requises : NOTION_TOKEN, BOOND_USER_TOKEN, BOOND_CLIENT_TOKEN, BOOND_CLIENT_KEY
"""

import requests
import jwt
import time
import os
from datetime import datetime

# CONFIG
NOTION_TOKEN       = os.environ.get("NOTION_TOKEN", "ntn_p90221127079Pdk37Ceu8FATZx9OYoYzW7vYwBLGcX0dEP")
NOTION_DB_ID       = "cf9ce4665b1745e9a92e2f784a053bb0"
BOOND_URL          = "https://ui.boondmanager.com/api"
BOOND_USER_TOKEN   = os.environ.get("BOOND_USER_TOKEN", "3232372e616c70696e656f")
BOOND_CLIENT_TOKEN = os.environ.get("BOOND_CLIENT_TOKEN", "616c70696e656f")
BOOND_CLIENT_KEY   = os.environ.get("BOOND_CLIENT_KEY", "fd2824bfbbaa36b2460c")

# Mapping 100% verifie dans Boond
CANDIDATE_TYPES = {
    "Note":                      13,
    "Pr\u00e9qualification":     44,
    "Prequalification":          44,
    "Pr\u00e9paration qualification": 7,
    "Preparation qualification": 7,
    "Brief E2":                  25,
    "Entretien 1":               12,
    "Entretien 2":               40,
    "Entretien 3":               6,
    "QM BM":                     42,
    "QM Recruteur":              29,
}

def get_boond_headers():
    payload = {
        "userToken": BOOND_USER_TOKEN,
        "clientToken": BOOND_CLIENT_TOKEN,
        "time": int(time.time()),
        "mode": "normal"
    }
    token = jwt.encode(payload, BOOND_CLIENT_KEY, algorithm="HS256")
    return {"X-Jwt-Client-BoondManager": token, "Content-Type": "application/json"}

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def get_pending_entries():
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    payload = {"filter": {"property": "Envoy\u00e9 vers Boond", "checkbox": {"equals": False}}}
    r = requests.post(url, headers=notion_headers, json=payload)
    r.raise_for_status()
    return r.json().get("results", [])

def extract_entry_data(page):
    props = page["properties"]
    def get_text(p):
        rich = props.get(p, {}).get("rich_text", [])
        return rich[0]["plain_text"] if rich else ""
    def get_select(p):
        sel = props.get(p, {}).get("select")
        return sel["name"] if sel else ""
    def get_title(p):
        title = props.get(p, {}).get("title", [])
        return title[0]["plain_text"] if title else ""
    def get_date(p):
        date = props.get(p, {}).get("date")
        return date["start"] if date else datetime.now().strftime("%Y-%m-%d")
    return {
        "page_id":      page["id"],
        "titre":        get_title("Titre"),
        "candidat":     get_text("Candidat / Collaborateur"),
        "type_echange": get_select("Type d'\u00e9change"),
        "date":         get_date("Date"),
        "resume":       get_text("R\u00e9sum\u00e9"),
    }

def get_rich_text(rich):
    """Convertit les rich_text Notion en HTML"""
    result = ""
    for t in rich:
        text = t.get("plain_text", "")
        ann = t.get("annotations", {})
        if ann.get("bold"):
            text = f"<strong>{text}</strong>"
        if ann.get("italic"):
            text = f"<em>{text}</em>"
        result += text
    return result

def get_page_content(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    r = requests.get(url, headers=notion_headers)
    r.raise_for_status()
    blocks = r.json().get("results", [])
    html_parts = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        btype = block.get("type")
        rich = block.get(btype, {}).get("rich_text", []) if btype else []
        text = get_rich_text(rich)

        if btype == "heading_1" and text.strip():
            html_parts.append(f"<h2><strong>{text}</strong></h2>")
        elif btype == "heading_2" and text.strip():
            html_parts.append(f"<h3><strong>{text}</strong></h3>")
        elif btype == "heading_3" and text.strip():
            html_parts.append(f"<h3>{text}</h3>")
        elif btype == "paragraph":
            if text.strip():
                html_parts.append(f"<p>{text}</p>")
            else:
                html_parts.append("<br>")
        elif btype == "bulleted_list_item":
            # Regroupe les items de liste consecutifs
            items = []
            while i < len(blocks) and blocks[i].get("type") == "bulleted_list_item":
                r2 = blocks[i].get("bulleted_list_item", {}).get("rich_text", [])
                items.append(f"<li>{get_rich_text(r2)}</li>")
                i += 1
            html_parts.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif btype == "numbered_list_item":
            items = []
            while i < len(blocks) and blocks[i].get("type") == "numbered_list_item":
                r2 = blocks[i].get("numbered_list_item", {}).get("rich_text", [])
                items.append(f"<li>{get_rich_text(r2)}</li>")
                i += 1
            html_parts.append("<ol>" + "".join(items) + "</ol>")
            continue
        elif btype == "divider":
            html_parts.append("<hr>")
        i += 1
    return "".join(html_parts)

def search_in_boond(full_name):
    parts = full_name.strip().split(" ", 1)
    if len(parts) < 2:
        print(f"  Nom incomplet : '{full_name}'")
        return None
    prenom, nom = parts[0], parts[1]
    hdrs = get_boond_headers()

    r = requests.get(f"{BOOND_URL}/resources", headers=hdrs,
                     params={"keywords": full_name, "maxResults": 5, "page": 1})
    if r.status_code == 200:
        for item in r.json().get("data", []):
            attrs = item.get("attributes", {})
            if prenom.lower() == attrs.get("firstName","").lower().strip() and \
               nom.lower() == attrs.get("lastName","").lower().strip():
                cid = item.get("id")
                print(f"  Collaborateur trouve : {full_name} (ID: {cid})")
                return {"type": "resource", "id": cid}

    r2 = requests.get(f"{BOOND_URL}/candidates", headers=hdrs,
                      params={"keywords": full_name, "maxResults": 5, "page": 1})
    if r2.status_code == 200:
        for item in r2.json().get("data", []):
            attrs = item.get("attributes", {})
            if prenom.lower() == attrs.get("firstName","").lower().strip() and \
               nom.lower() == attrs.get("lastName","").lower().strip():
                cid = item.get("id")
                print(f"  Candidat trouve : {full_name} (ID: {cid})")
                return {"type": "candidate", "id": cid}

    print(f"  Personne trouvee dans Boond pour : '{full_name}'")
    return None

def create_boond_action(person, entry, content):
    dep_type = person["type"]
    typeof_boond = CANDIDATE_TYPES.get(entry["type_echange"], 13)
    resume = entry["resume"] or content or f"Transcription Notion - {entry['titre']}"
    action_body = {
        "data": {
            "type": "action",
            "attributes": {
                "typeOf": typeof_boond,
                "startDate": f"{entry['date']}T09:00:00+0200",
                "text": f"[{entry['type_echange']}] {entry['titre']}\n\n{resume}"
            },
            "relationships": {
                "dependsOn": {"data": {"type": dep_type, "id": str(person["id"])}}
            }
        }
    }
    r = requests.post(f"{BOOND_URL}/actions", headers=get_boond_headers(), json=action_body)
    print(f"  Creation action Boond : {r.status_code}")
    if r.status_code in [200, 201]:
        action_id = r.json().get("data", {}).get("id", "?")
        print(f"  Action creee (ID: {action_id})")
        return action_id
    else:
        print(f"  Erreur : {r.text[:300]}")
        return None

def mark_as_sent(page_id, boond_action_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "Envoy\u00e9 vers Boond": {"checkbox": True},
            "Statut": {"select": {"name": "Envoy\u00e9 Boond"}},
            "ID Boond": {"rich_text": [{"text": {"content": str(boond_action_id)}}]}
        }
    }
    requests.patch(url, headers=notion_headers, json=payload)

def main():
    print(f"Notion -> Boond | {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    r = requests.get(f"{BOOND_URL}/application/current-user", headers=get_boond_headers())
    if r.status_code != 200:
        print(f"Erreur connexion Boond : {r.status_code}")
        return

    entries = get_pending_entries()
    if not entries:
        print("Aucune entree a traiter.")
        return

    print(f"{len(entries)} entretien(s) a synchroniser")
    success, errors = 0, 0
    for page in entries:
        entry = extract_entry_data(page)
        print(f"> {entry['titre']} - {entry['candidat']} ({entry['type_echange']})")
        if not entry["candidat"]:
            errors += 1
            continue
        content = "" if entry["resume"] else get_page_content(entry["page_id"])
        person = search_in_boond(entry["candidat"])
        if not person:
            errors += 1
            continue
        action_id = create_boond_action(person, entry, content)
        if not action_id:
            errors += 1
            continue
        mark_as_sent(entry["page_id"], action_id)
        success += 1

    print(f"OK: {success} | ERREUR: {errors}")

if __name__ == "__main__":
    main()
    input("\nAppuie sur Entree pour fermer...")
