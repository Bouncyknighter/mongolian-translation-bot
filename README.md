# Mongolian Book Translation Bot

Translates English PDF books to Mongolian using local LLM (Ollama) with a 3-stage pipeline.

## Pipeline Stages

1. **Stage 1 - Extract & Translate**: Extracts text from PDFs, batches English sentences, translates to Mongolian via Ollama API
2. **Stage 2 - Refine**: Polishes Mongolian translations for natural flow (saves to `post_processing/*_refined.json`)
3. **Stage 3 - Assemble**: Generates PDF and EPUB from refined translations

## Folder Structure

```
ENG books/              # Input PDFs
translation_cache/      # Stage 1: Extracted + translated blocks (*_structural.json)
post_processing/        # Stage 2: Refined Mongolian (*_refined.json) ← NVIDIA training data
final_processed_books/  # Stage 3: Output PDFs and EPUBs
```

## Setup

```bash
pip install -r requirements.txt
# Ensure Ollama is running at http://192.168.1.137:11434
```

## Usage

```bash
python3 main.py
```

The bot processes books **one at a time** (completes all 3 stages per book before moving to next). It auto-detects existing progress and resumes from interruptions.

## Resume Logic

- PDF exists (>10KB) → Skip book
- Refined JSON exists (>1KB) → Assembly only
- Structural JSON exists (>1KB) → Patch → Refine → Assembly
- Nothing exists → Full pipeline

## Files

- `main.py` - Main orchestrator with resume logic
- `assemble.py` - Stage 2 (refine) + Stage 3 (PDF/EPUB generation)
- `requirements.txt` - Dependencies
