#!/usr/bin/env python3
"""
Mongolian Book Translation Pipeline
One book at a time: Stage 1 → 2 → 3 completely before next book.
"""

import fitz
import requests
import json
import time
import re
import os
import logging
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from pathlib import Path
import assemble

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://192.168.1.137:11434/api/generate"
MODEL_NAME = "deepseek-v3.2:cloud"

INPUT_FOLDER = os.path.join(SCRIPT_DIR, "ENG books")
CACHE_FOLDER = os.path.join(SCRIPT_DIR, "translation_cache")
POST_PROCESS_FOLDER = os.path.join(SCRIPT_DIR, "post_processing")
FINAL_BOOK_FOLDER = os.path.join(SCRIPT_DIR, "final_processed_books")

for folder in [CACHE_FOLDER, POST_PROCESS_FOLDER, FINAL_BOOK_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "translation_log.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- API SESSION ---
def get_robust_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=3, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

session = get_robust_session()

# --- UTILS ---
def extract_json(text):
    try:
        text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            json_str = match.group(0)
            json_str = re.sub(r',\s*\}', '}', json_str)
            json_str = re.sub(r',\s*\]', ']', json_str)
            return json.loads(json_str)
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}")
    return None

def heal_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def split_sentences(text):
    if not text: return []
    raw_splits = re.split(r'([.!?])\s+', text)
    sentences = []
    current = ""
    abbreviations = {"Mr", "Mrs", "Ms", "Dr", "St", "a", "p", "v", "vs", "Inc", "Ltd", "Corp"}
    
    for i in range(0, len(raw_splits) - 1, 2):
        chunk = raw_splits[i]
        punc = raw_splits[i+1]
        current += chunk + punc
        words = chunk.split()
        last_word = words[-1] if words else ""
        if last_word not in abbreviations:
            sentences.append(current.strip())
            current = ""
    
    if current:
        if len(raw_splits) % 2 != 0:
            current += raw_splits[-1]
        sentences.append(current.strip())
    elif len(raw_splits) % 2 != 0:
        sentences.append(raw_splits[-1].strip())
    
    return [s for s in sentences if len(s) > 2]

def translate_sentence_batch(all_sentences, book_title, chapter_context):
    if not all_sentences: return []
    
    system_persona = (
        f"You are a master Mongolian literary translator. Book: '{book_title}'. Context: {chapter_context}. "
        "Translate English to formal Mongolian Cyrillic. Maintain narrative tone. "
        'Return ONLY a JSON list of objects: {"translations": [{"en": "...", "mn": "..."}]}'
    )
    
    list_input = "\n".join([f"{s}" for s in all_sentences])
    
    try:
        response = session.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": f"{system_persona}\n\nEnglish Sentences:\n{list_input}",
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 4096}
            },
            timeout=300
        )
        response.raise_for_status()
        data = response.json()
        result = extract_json(data.get("response", "{}"))
        return result.get("translations", []) if result else []
    except Exception as e:
        logger.error(f"Batch API Error: {e}")
        return []

# --- STAGE 1 ---
def get_page_structure(page, book_name):
    blocks = []
    page_dict = page.get_text("dict")
    img_dir = os.path.join(CACHE_FOLDER, "images", book_name)
    os.makedirs(img_dir, exist_ok=True)
    
    font_sizes = []
    for b in page_dict["blocks"]:
        if "lines" in b:
            for l in b["lines"]:
                for s in l["spans"]:
                    if s["text"].strip():
                        font_sizes.append(s["size"])
    
    base_size = sum(font_sizes) / len(font_sizes) if font_sizes else 11

    for i, b in enumerate(page_dict["blocks"]):
        if b["type"] == 1:
            image_filename = f"img_{page.number}_{i}.png"
            image_path = os.path.join(img_dir, image_filename)
            try:
                if "image" in b:
                    with open(image_path, "wb") as f:
                        f.write(b["image"])
                    blocks.append({"type": "image", "path": image_path, "content": []})
                elif "xref" in b:
                    pix = fitz.Pixmap(page.parent, b["xref"])
                    if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                    pix.save(image_path)
                    blocks.append({"type": "image", "path": image_path, "content": []})
            except: pass
            continue

        if "lines" not in b: continue
        
        block_text = ""
        max_size = 0
        is_bold = False
        
        for l in b["lines"]:
            for s in l["spans"]:
                span_text = s["text"].strip()
                if not span_text: continue
                block_text += " " + span_text
                max_size = max(max_size, s["size"])
                if "bold" in s["font"].lower(): is_bold = True
        
        cleaned_text = heal_text(block_text)
        if not cleaned_text: continue
        
        block_type = "paragraph"
        if max_size > base_size * 1.25 or (is_bold and len(cleaned_text) < 200):
            block_type = "heading"
        
        blocks.append({
            "type": block_type,
            "text": cleaned_text,
            "sentences": split_sentences(cleaned_text),
            "content": []
        })
    return blocks

def process_book_stage1(pdf_path, book_name, safe_name):
    cache_path = os.path.join(CACHE_FOLDER, f"{safe_name}_structural.json")
    
    if os.path.exists(cache_path):
        logger.info(f"  ✅ Stage 1 already done")
        return cache_path
    
    logger.info(f"  🚀 Stage 1: Extracting...")
    doc = fitz.open(pdf_path)
    full_structure = []
    current_chapter = "Unknown"
    pending_sentences = []
    pending_blocks = []

    def flush_batch():
        nonlocal pending_sentences, pending_blocks
        if not pending_sentences: return
        
        translations = translate_sentence_batch(pending_sentences, book_name, current_chapter)
        mapping = {t["en"]: t["mn"] for t in translations if "en" in t and "mn" in t}
        
        for block in pending_blocks:
            for en in block["sentences"]:
                mn = mapping.get(en, "")
                if mn and not mn.endswith(('.', '!', '?')): mn += "."
                block["content"].append({"en": en, "mn": mn})
            full_structure.append({
                "page": block["page"],
                "type": block["type"],
                "content": block["content"],
                "path": block.get("path")
            })
            block.pop("sentences", None)
            block.pop("page", None)
        
        pending_sentences = []
        pending_blocks = []

    for page_num in range(len(doc)):
        if page_num % 50 == 0:
            logger.info(f"    Page {page_num + 1}/{len(doc)}")
        
        page_blocks = get_page_structure(doc[page_num], safe_name)
        
        for block in page_blocks:
            if block["type"] == "heading":
                current_chapter = block["text"]
            
            if block["type"] == "image":
                full_structure.append({
                    "page": page_num + 1,
                    "type": "image",
                    "path": block["path"],
                    "content": []
                })
                continue

            block["page"] = page_num + 1
            pending_blocks.append(block)
            pending_sentences.extend(block["sentences"])
            
            if len(pending_sentences) >= 30:
                flush_batch()
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(full_structure, f, ensure_ascii=False, indent=4)

    flush_batch()
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(full_structure, f, ensure_ascii=False, indent=4)
    
    logger.info(f"  ✅ Stage 1 complete: {len(full_structure)} blocks")
    return cache_path

def patch_missing_translations(cache_path, book_title):
    logger.info(f"  🩹 Patching...")
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    modified_count = 0
    for block in data:
        if block["type"] in ["paragraph", "heading"]:
            for item in block["content"]:
                if not item.get("mn") or len(item["mn"]) < 3:
                    res = translate_sentence_batch([item["en"]], book_title, "Patching")
                    if res and res[0].get("mn"):
                        item["mn"] = res[0]["mn"]
                        if not item["mn"].endswith(('.', '!', '?')): item["mn"] += "."
                        modified_count += 1
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
    
    if modified_count > 0:
        logger.info(f"    Patched {modified_count} sentences")
    else:
        logger.info(f"    No patches needed")
    return data

def is_valid_file(path, min_size=100):
    """Check if file exists and has meaningful content."""
    return os.path.exists(path) and os.path.getsize(path) > min_size

def process_single_book(pdf_path):
    """Process one book: Stage 1 → Patch → Stage 2/3 completely."""
    book_name = pdf_path.stem
    safe_name = re.sub(r'[^\w\s-]', '', book_name).strip().replace(' ', '_')
    
    cache_path = os.path.join(CACHE_FOLDER, f"{safe_name}_structural.json")
    refined_path = os.path.join(POST_PROCESS_FOLDER, f"{safe_name}_refined.json")
    pdf_final_path = os.path.join(FINAL_BOOK_FOLDER, f"{safe_name}_Final.pdf")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📚 [{book_name}]")
    logger.info(f"{'='*60}")
    
    # === CHECK 1: Final PDF exists and is valid ===
    if is_valid_file(pdf_final_path, 10000):  # PDF should be >10KB
        logger.info(f"✅ PDF complete ({os.path.getsize(pdf_final_path)//1024}KB) - skipping")
        return
    elif os.path.exists(pdf_final_path):
        logger.info(f"⚠️ PDF exists but too small ({os.path.getsize(pdf_final_path)} bytes) - reprocessing")
        os.remove(pdf_final_path)
    
    # === CHECK 2: Refined JSON exists but no PDF ===
    # This means refinement finished but assembly was interrupted
    if is_valid_file(refined_path, 1000):
        logger.info(f"🔄 Refined JSON found ({os.path.getsize(refined_path)//1024}KB) - Assembly only")
        with open(refined_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        logger.info(f"🎬 Stage 3: Assembling...")
        assemble.assemble_pdf(book_data, safe_name)
        assemble.assemble_epub(book_data, safe_name)
        logger.info(f"✅ Book complete!")
        return
    elif os.path.exists(refined_path):
        logger.info(f"⚠️ Refined JSON too small - will re-refine")
        os.remove(refined_path)
    
    # === CHECK 3: Structural JSON exists ===
    if not is_valid_file(cache_path, 1000):
        # Stage 1: Extract and translate
        process_book_stage1(str(pdf_path), book_name, safe_name)
    else:
        logger.info(f"🔄 Structural JSON found ({os.path.getsize(cache_path)//1024}KB)")
    
    # Patch missing translations
    book_data = patch_missing_translations(cache_path, book_name)
    
    # Stage 2 & 3: Refine + Assemble
    logger.info(f"🎬 Stage 2/3: Refining + Assembling...")
    assemble.process_single_book(book_data, safe_name)
    
    logger.info(f"✅ Book complete!")

def main():
    books = sorted(list(Path(INPUT_FOLDER).glob("*.pdf")))
    logger.info(f"\n📚 Found {len(books)} books")
    logger.info(f"Mode: One book at a time (1→2→3)\n")
    
    for i, book in enumerate(books, 1):
        logger.info(f"\n[{i}/{len(books)}] Starting...")
        try:
            process_single_book(book)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info("🎉 All books processed!")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    main()
