#!/usr/bin/env python3
"""
Stage 2 & 3: Refinement and Assembly
Takes structural JSON, refines translations, generates PDF/EPUB.
"""

import json
import os
import re
import logging
import requests
import time
from pathlib import Path
from fpdf import FPDF

try:
    from fpdf import XPos, YPos
except ImportError:
    XPos = None
    YPos = None

try:
    from ebooklib import epub
    EPUB_AVAILABLE = True
except ImportError:
    EPUB_AVAILABLE = False

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://192.168.1.137:11434/api/generate"
MODEL_NAME = "deepseek-v3.2:cloud"

CACHE_FOLDER = os.path.join(SCRIPT_DIR, "translation_cache")
POST_PROCESS_FOLDER = os.path.join(SCRIPT_DIR, "post_processing")
FINAL_BOOK_FOLDER = os.path.join(SCRIPT_DIR, "final_processed_books")
FONT_PATH = os.path.join(SCRIPT_DIR, "NotoSans-Regular.ttf")
BOLD_FONT_PATH = os.path.join(SCRIPT_DIR, "NotoSans-Bold.ttf")

# Create folders
for folder in [POST_PROCESS_FOLDER, FINAL_BOOK_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "assembly_log.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- UTILS ---
def extract_json(text):
    try:
        text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}")
    return None

def refine_chunk(blocks_chunk, book_title, chunk_index, total_chunks):
    """Refines a specific chunk of blocks."""
    if not blocks_chunk: return blocks_chunk
    
    input_text = ""
    for b in blocks_chunk:
        for item in b["content"]:
            input_text += f"{item['mn']}\n"
    
    if not input_text.strip(): return blocks_chunk

    logger.info(f"  ✨ Refining chunk {chunk_index}/{total_chunks} ({len(input_text)} chars)...")
    
    system_persona = (
        f"You are a master Mongolian book editor. Polishing '{book_title}'. "
        "Goal: Polished, professional Mongolian literature. "
        'Return JSON: {"refined_mn": ["...", "..."]}'
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": f"{system_persona}\n\nSentences:\n{input_text}",
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.2, "num_ctx": 8192}
            },
            timeout=500
        )
        response.raise_for_status()
        data = response.json()
        result = extract_json(data.get("response", "{}"))
        refined_list = result.get("refined_mn", [])
        
        # Map refined text back
        idx = 0
        for b in blocks_chunk:
            for item in b["content"]:
                if idx < len(refined_list):
                    item["mn"] = refined_list[idx]
                    idx += 1
        
        return blocks_chunk
    except Exception as e:
        logger.error(f"  Refinement error: {e}")
        return blocks_chunk

def refine_narrative_chunked(blocks, book_title):
    """Refines the whole book in chunks."""
    if not blocks: return []
    
    translatable_blocks = [b for b in blocks if b["type"] in ["paragraph", "heading"] and b["content"]]
    if not translatable_blocks: return blocks

    chunk_size = 15
    total_chunks = (len(translatable_blocks) + chunk_size - 1) // chunk_size
    
    logger.info(f"📖 Refining '{book_title}' in {total_chunks} chunks")
    
    for i in range(0, len(translatable_blocks), chunk_size):
        chunk = translatable_blocks[i:i + chunk_size]
        refine_chunk(chunk, book_title, (i // chunk_size) + 1, total_chunks)
        time.sleep(0.5)
        
    return blocks

# --- BOOK GENERATORS ---
class RichMongolianPDF(FPDF):
    def __init__(self, font_regular, font_bold):
        super().__init__()
        self.add_font("NotoSans", "", font_regular)
        self.add_font("NotoSans", "B", font_bold)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("NotoSans", "", 8)
        self.cell(0, 10, "English-Mongolian Translation", 0, align='C')

def assemble_pdf(book_data, book_name):
    """Generate PDF from refined book data."""
    pdf = RichMongolianPDF(FONT_PATH, BOLD_FONT_PATH)
    pdf.add_page()
    
    for block in book_data:
        if block["type"] == "image":
            if os.path.exists(block.get("path", "")):
                try:
                    pdf.image(block["path"], x=20, w=170)
                    pdf.ln(5)
                except:
                    pass
            continue

        is_header = block["type"] == "heading"
        pdf.set_font("NotoSans", "B" if is_header else "", 14 if is_header else 11)
        
        combined_text = " ".join([item["mn"] for item in block["content"] if item.get("mn")])
        if not combined_text:
            combined_text = " ".join([item["en"] for item in block["content"]])
             
        if is_header:
            pdf.multi_cell(0, 10, combined_text, align='C')
            pdf.ln(5)
        else:
            pdf.multi_cell(0, 7, combined_text)
            pdf.ln(2)
            
    output_path = os.path.join(FINAL_BOOK_FOLDER, f"{book_name}_Final.pdf")
    pdf.output(output_path)
    logger.info(f"  📄 PDF: {output_path}")

def assemble_epub(book_data, book_name):
    """Generate EPUB from refined book data."""
    if not EPUB_AVAILABLE:
        logger.warning("  EPUB skipped: ebooklib not installed")
        return
    
    book = epub.EpubBook()
    book.set_identifier(f"id_{book_name}")
    book.set_title(book_name.replace("_", " "))
    book.set_language('mn')

    chapters = []
    current_chapter = None
    current_content = ""

    for i, block in enumerate(book_data):
        if block["type"] == "image":
            if os.path.exists(block.get("path", "")):
                img_name = os.path.basename(block["path"])
                img_item = epub.EpubImage()
                img_item.file_name = f'images/{img_name}'
                with open(block["path"], 'rb') as f: 
                    img_item.content = f.read()
                book.add_item(img_item)
                current_content += f'<div><img src="images/{img_name}" /></div>'
            continue

        if block["type"] == "heading" or i == 0:
            if current_chapter:
                current_chapter.content = current_content
                book.add_item(current_chapter)
                chapters.append(current_chapter)
            
            title = " ".join([item["mn"] for item in block["content"] if item.get("mn")]) or "Chapter"
            current_chapter = epub.EpubHtml(title=title, file_name=f'chap_{len(chapters)}.xhtml', lang='mn')
            current_content = f"<h1>{title}</h1>"
        else:
            text = " ".join([item["mn"] for item in block["content"] if item.get("mn")])
            if text: 
                current_content += f"<p>{text}</p>"

    if current_chapter:
        current_chapter.content = current_content
        book.add_item(current_chapter)
        chapters.append(current_chapter)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    
    output_path = os.path.join(FINAL_BOOK_FOLDER, f"{book_name}.epub")
    epub.write_epub(output_path, book, {})
    logger.info(f"  📖 EPUB: {output_path}")

def process_single_book(book_data, book_name):
    """Process a single book: refine + assemble."""
    logger.info(f"🎬 Stage 2/3: Refining and assembling {book_name}")
    
    # Stage 2: Refinement
    refined_data = refine_narrative_chunked(book_data, book_name)
    
    # Save refined state
    ref_path = os.path.join(POST_PROCESS_FOLDER, f"{book_name}_refined.json")
    with open(ref_path, "w", encoding="utf-8") as f:
        json.dump(refined_data, f, ensure_ascii=False, indent=4)
    
    # Stage 3: Assembly
    assemble_pdf(refined_data, book_name)
    assemble_epub(refined_data, book_name)
    
    logger.info(f"✅ Assembly complete: {book_name}")

def process_all():
    """Process all structural JSON files in cache folder."""
    files = list(Path(CACHE_FOLDER).glob("*_structural.json"))
    logger.info(f"Found {len(files)} books to assemble\n")
    
    for i, file_path in enumerate(files, 1):
        book_name = file_path.stem.replace("_structural", "")
        logger.info(f"[{i}/{len(files)}] {book_name}")
        
        # Check if already done
        pdf_path = os.path.join(FINAL_BOOK_FOLDER, f"{book_name}_Final.pdf")
        if os.path.exists(pdf_path):
            logger.info(f"  ✅ Already complete - skipping\n")
            continue
        
        with open(file_path, "r", encoding="utf-8") as f:
            book_data = json.load(f)
        
        process_single_book(book_data, book_name)
        logger.info("")
    
    logger.info("🎉 All assemblies complete!")

if __name__ == "__main__":
    process_all()
