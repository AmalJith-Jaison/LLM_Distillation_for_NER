import os
import json
import email
from email import policy
from bs4 import BeautifulSoup

# ==========================================================
# STEP 1: Extract email content
# ==========================================================
def extract_eml_info(file_path):
    with open(file_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    subject = msg.get("subject", "")
    from_ = msg.get("from", "")
    to = msg.get("to", "")
    date = msg.get("date", "")
    body_plain = ""
    body_text = ""
    tables = []
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                body_plain += part.get_content()
            elif content_type == "text/html":
                html_content = part.get_content()
                soup = BeautifulSoup(html_content, "html.parser")
                body_text += soup.get_text(separator="\n", strip=True)

                for table in soup.find_all("table"):
                    rows = []
                    for tr in table.find_all("tr"):
                        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        if cells:
                            rows.append(cells)
                    if rows:
                        tables.append(rows)
            elif part.get_filename():
                attachments.append(part.get_filename())
    else:
        if msg.get_content_type() == "text/plain":
            body_plain = msg.get_content()
            body_text = body_plain
        elif msg.get_content_type() == "text/html":
            html_content = msg.get_content()
            soup = BeautifulSoup(html_content, "html.parser")
            body_text = soup.get_text(separator="\n", strip=True)
            for table in soup.find_all("table"):
                rows = []
                for tr in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if cells:
                        rows.append(cells)
                if rows:
                    tables.append(rows)

    return {
        "filename": os.path.basename(file_path),
        "subject": subject,
        "from": from_,
        "to": to,
        "date": date,
        "body": (
            body_plain.strip()
            + "\n"
            + body_text.strip()
            + "\n"
            + "\n".join([", ".join(row) for table in tables for row in table])
            + "\n"
            + "\n".join(attachments)
        ).strip(),
    }

# ==========================================================
# STEP 2: Process folder → JSON
# ==========================================================
def process_eml_folder(folder_path):
    data = []
    total_files = 0
    processed_files = 0

    for file in os.listdir(folder_path):
        if file.lower().endswith(".eml"):
            total_files += 1
            eml_path = os.path.join(folder_path, file)
            info = extract_eml_info(eml_path)
            if info:
                data.append(info)
                processed_files += 1
            else:
                print(f"❌ Skipped {file}")

    output_json = os.path.join(folder_path, "emails.json")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"\n📊 Processed {processed_files}/{total_files} emails")
    print(f"✅ Output JSON: {output_json}")
    return output_json

# ==========================================================
# STEP 3: JSON → Prompt templates
# ==========================================================
def make_prompts(input_json):
    with open(input_json, "r", encoding="utf-8") as f:
        emails = json.load(f)

    template = """You are assisting the Airline Cargo team in extracting specific business-critical entities from customer emails.
Each email consists of a subject and body, both delimited by triple backticks (```), and may be written in various languages.  
 
Your task: Extract only the requested fields and return them in a JSON array of dictionaries, each representing one Air Waybill (AWB) entry.  
 
❗ Strict Rules:
- Only extract values from the provided email subject and body.  
- Do not assume or fabricate values.  
- If a field is missing, use "" (for strings), 0 (for numbers), or [] (for lists).  
- Translate all extracted non-English text into English.  
- Return only the JSON output — no explanations, no markdown, no backticks, no extra text.  
- One dictionary per AWB; multiple AWBs = multiple dictionaries.  
input mail:
 
filename: {filename}
Subject: {subject}
From: {from_}
To: {to}
Body: {body}
--- **Do not take any values outside "input mail"** ---
Output format:
 
[
    {{
        "AWB": "",
        "Language": "",
        "Flight_details": [
            {{
                "FlightNo": "",
                "Departure-date": "",
                "Source": "",
                "Destination": ""
            }}
        ],
        "dropOff-date": "",
        "total-pieces": 0,
        "pieces@dimensions": [""],
        "dimension-unit": [""],
        "Weight": 0,
        "chargeable-weight": 0,
        "weight-unit": "",
        "Volume": 0,
        "volume-unit": "",
        "volume_weight": "",
        "special-instruction": "",
        "commodity-description": "",
        "shipment-description": "",
        "product-code": "",
        "SCC": "",
        "Source": "",
        "Destination": "",
        "Temperature": [
            {{
                "min": 0,
                "max": 0
            }}
        ]
    }}
]  
 
---  
Field rules:  
 
AWB: Must be 11-digit numbers starting with valid airline prefixes. May be called MAWB or GUIA. Remove hyphens/spaces.  
 
Language: Detect primary language of email (subject + body). Return full name (e.g., "English", "German", "Japanese"). If cannot detect confidently, return "".  
 
Flight_details: A list of dictionaries, one per flight segment.  
- "FlightNo" → airline code + number . Ignore attached dates. If only airline code and no number is provided, return ""
- "Departure-date" → YYYY-MM-DD (assume 2025 if year missing).  
- "Source" / "Destination" → IATA codes.  
- Multiple flights = multiple dictionaries.  
 
dropOff-date: Extract drop-off / delivery / handover date in YYYY-MM-DD (assume 2025 if year missing).  
 
total-pieces: Integer for cargo pieces.  
 
pieces@dimensions: Format like ["piece@dimensionsxdimensionsxdimensions"] or ["piece@dimensionsxdimensionsxdimensions@weight"].  
- If pieces & weights separate (e.g., weight + dimension x dimension x dimension X piece), match them correctly → ["piece@dimension x dimension x dimension@weight"].  
- Do not fabricate rows. 
- Do not fabricate information

dimension-unit: Units as list ("CM", "M", "IN", "OTH"), matching sequence.  
 
Weight: Total cargo weight. Use Gross Weight (G/W) if given.  
 
chargeable-weight: Explicit if present; else max(Weight, volume_weight).  
 
weight-unit: One of "KG", "KGS", "LBS", "OTH".  
 
Volume: Extract only if explicitly given . Do not compute.  
 
volume-unit: One of "CBM", "CFT", "M3", "OTH".  
 
volume_weight: Extract explicitly if labeled "VW", "V/W", or "volume weight".  
 
special-instruction: Extract handling notes. Translate to English.  
 
commodity-description: Extract description of goods (translated).  
 
shipment-description: Same value as commodity-description.  
 
product-code: If not provided, infer from commodity-description:  
- "GEN" = General cargo  
- "HAZ" = Hazardous materials  
- "DG" = Dangerous goods  
 
SCC: Extract if explicitly given (SCC, SHC, or special handling code). Else "".  
 
Source / Destination: Extract from IATA codes like.
 
Temperature: if any temperature value contains a combination of plus and minus symbol interpret as a range.
- If range: "LT-UT°C" → {{"min": LT, "max": UT}}  
- If single: "T°C" → {{"min": T, "max": T}}  
- If none: {{"min": 0, "max": 0}}

 
Return only the JSON output. Do not include backticks, explanations, or any extra text."""
    prompts = []
    for entry in emails:
        filled_string = template.format(
            filename=entry.get("filename", ""),
            subject=entry.get("subject", ""),
            from_=entry.get("from", ""),
            to=entry.get("to", ""),
            body=entry.get("body", ""),
        )
        prompts.append({"prompt": filled_string})

    output_json = os.path.join(os.path.dirname(input_json), "email_prompts.json")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(prompts, f, indent=4, ensure_ascii=False)

    print(f"✅ Saved {len(prompts)} prompts: {output_json}")
    return output_json

# ==========================================================
# STEP 4: Prompts → JSONL
# ==========================================================
def prompts_to_jsonl(input_json):
    output_jsonl = os.path.join(os.path.dirname(input_json), "prompts_golden.jsonl")
    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(output_jsonl, "w", encoding="utf-8") as f:
        for entry in data:
            prompt_text = entry.get("prompt", "").strip()
            jsonl_entry = {
                "schemaVersion": "bedrock-conversation-2024",
                "messages": [
                    {"role": "user", "content": [{"text": prompt_text}]}
                ],
            }
            f.write(json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

    print(f"✅ Converted {len(data)} prompts into {output_jsonl}")

# ==========================================================
# MAIN
# ==========================================================
if __name__ == "__main__":
    eml_folder = r""  #input folder

    # 1. Process all emails → JSON
    emails_json = process_eml_folder(eml_folder)

    # 2. JSON → prompts
    prompts_json = make_prompts(emails_json)

    # 3. Prompts → JSONL
    prompts_to_jsonl(prompts_json)

