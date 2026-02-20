# Mongolian Translation Scripts - FIXES APPLIED

## Date: 2026-02-14

---

## PROBLEMS IDENTIFIED

### Problem 1: Books Processed All-At-Once (Not One-by-One)
**Original Behavior:**
- Stage 1: Extract/translate ALL books first
- Stage 2: Patch ALL books
- Stage 3: Refine ALL books
- Stage 4: Assemble ALL books

**Issue:** No book was complete until all books were done. If process crashed, no final PDFs existed.

### Problem 2: Refined Text Not Saved to Final PDF
**Original Bug:**
- `refine_narrative_chunked()` modified blocks in place but didn't return the full dataset
- Image blocks were filtered out during refinement
- Final PDF used original (unrefined) text for some blocks

### Problem 3: JSON Training Data Location
**Found:** 13 books of parallel corpus data in `translation_cache/*_structural.json`

---

## FIXES APPLIED

### Fix 1: Sequential Book Processing (One-by-One)

**New Behavior:**
```
Book 1: Stage 1 → Patch → Refine → PDF/EPUB → DONE
Book 2: Stage 1 → Patch → Refine → PDF/EPUB → DONE
Book 3: Stage 1 → Patch → Refine → PDF/EPUB → DONE
```

**Implementation:**
- `process_single_book_completely()` function in `main_fixed.py`
- Each book goes through complete pipeline before next starts
- If crash occurs, completed books have final PDFs/EPUBs

**Code Change in main.py:**
```python
def process_single_book_completely(pdf_path):
    """Process ONE book completely through all stages before moving to next."""
    # Stage 1: Extract/translate
    cache_path = process_book_stage1(str(pdf_path), book_name, safe_name)
    
    # Patch missing translations
    book_data = patch_missing_translations(cache_path, book.stem)
    
    # Stage 2 & 3: Refinement and Assembly (ONE book at a time)
    assemble.process_single_book(book_data, safe_name)
```

---

### Fix 2: Proper Refined Text Handling

**Problem:** Refinement only processed `translatable_blocks` (paragraphs/headings) and lost image blocks.

**Solution in assemble_fixed.py:**
```python
def refine_narrative_chunked(all_blocks, book_title):
    """Refines in chunks but preserves ALL blocks including images."""
    # Create working copy
    blocks = [b.copy() for b in all_blocks]
    
    # Only refine translatable blocks
    for chunk in translatable_blocks:
        refined = refine_chunk(chunk, ...)
        # Copy refined text BACK to working copy
        blocks[orig_idx]["content"] = refined["content"]
    
    return blocks  # Returns ALL blocks with refined text
```

**PDF Assembly Fix:**
```python
# Prioritize refined mn text
for item in block.get("content", []):
    text = item.get("mn", "")  # Use Mongolian translation first
    if not text:
        text = item.get("en", "")  # Fallback to English
```

---

### Fix 3: JSON Training Data Sent

**File:** `mongolian_training_data.zip` (7.7 MB)
**Sent to:** Otoomoonoo@gmail.com
**Message ID:** 19c5a755fafe2568

**Contents:**
- 13 books with sentence-aligned EN-MN pairs
- Format: JSON with `{en: "...", mn: "..."}` structure
- Total: ~60MB uncompressed

**Books Included:**
1. The Anxious Generation
2. The Gene
3. The Minds I
4. Animal Farm & 1984
5. Brave New World
6. Complete Stories by Franz Kafka
7. Ed Thorp Quantitative Trading
8. The Female Brain
9. The Magic of Reality
10. The Man Who Mistook His Wife for a Hat
11. The Memory Police
12. The Metamorphosis
13. The Stranger

---

## FILES CREATED

| File | Purpose |
|------|---------|
| `main_fixed.py` | Fixed main script with one-by-one processing |
| `assemble_fixed.py` | Fixed assembly with proper refined text handling |
| `mongolian_training_data.zip` | Training data sent via email |

---

## HOW TO USE

### Option 1: Use Fixed Scripts (Recommended)

```bash
cd "~/Mongolian Translation Books"

# Backup original scripts
cp main.py main.py.backup
cp assemble.py assemble.py.backup

# Use fixed scripts
cp main_fixed.py main.py
cp assemble_fixed.py assemble.py

# Run with one-by-one processing
python3 main.py
```

### Option 2: Keep Original + Apply Fix Manually

Edit original `main.py`:
1. Change `main()` function to call `process_single_book_completely()` in loop
2. Remove the `assemble.process_assembly()` call at end
3. Add the new `process_single_book_completely()` function

---

## VERIFICATION

**Check current status:**
```bash
ls -la "final_processed_books/"
# Should see PDFs for completed books (processed one-by-one)

ls -la "post_processing/"
# Should see *_refined.json files
```

**Monitor processing:**
```bash
tail -f translation_log.log  # Stage 1 progress
tail -f assembly_log.log     # Stage 2/3 progress
```

---

## NEXT STEPS

1. **Test the fix:** Run on one small book first
2. **Monitor:** Check that refined text appears in PDF
3. **Review:** Check that books complete one by one
4. **Email sent:** Training data delivered to Otoomoonoo@gmail.com

---

## ARCHITECTURE COMPARISON

### OLD (Broken):
```
┌─────────────────────────────────────────────┐
│  Translate Book 1 → Translate Book 2 → ...   │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  Patch Book 1 → Patch Book 2 → ...           │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  Refine Book 1 → Refine Book 2 → ...        │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  Assemble PDFs (all at end)                  │
└─────────────────────────────────────────────┘
```

### NEW (Fixed):
```
Book 1: Translate → Patch → Refine → PDF → ✓ DONE
Book 2: Translate → Patch → Refine → PDF → ✓ DONE
Book 3: Translate → Patch → Refine → PDF → ✓ DONE
```

---

## TRAINING DATA FORMAT

```json
[
  {
    "page": 3,
    "type": "paragraph",
    "content": [
      {"en": "English sentence.", "mn": "Монгол өгүүлбэр."},
      {"en": "Another sentence.", "mn": "Өөр нэг өгүүлбэр."}
    ]
  }
]
```

This format is suitable for:
- Fine-tuning translation models
- Training LLMs on Mongolian-English parallel corpus
- Creating bilingual datasets

---

*Fixes applied by Zayaa - Personal AI Assistant*
