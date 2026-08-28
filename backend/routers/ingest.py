"""
Ingest router for Digitz AI.
Handles file upload, text extraction (with OCR fallback), chunking, embedding, indexing.
Supports PDF (including encrypted/scanned), DOCX, PPTX, CSV, TXT, Markdown, and images.
"""
import io
import os
import csv
import zipfile
import json
import sys
import xml.etree.ElementTree as ET
import asyncio
import time as _time

from fastapi import APIRouter, File, Form, Query, UploadFile, HTTPException
from fastapi.responses import PlainTextResponse
from core.db import (
    create_document,
    store_chunk_vector,
    delete_document,
    get_uploaded_files,
    get_upload_summary,
    reset_uploaded_documents,
    rename_document,
    get_document,
    update_document_status,
)
from core.llm_router import generate_embedding
from core.cache import invalidate_brand_cache
from core.logging import get_logger
from vectordb.chroma_store import store as chroma_store

logger = get_logger(__name__)

router = APIRouter(prefix='/ingest', tags=['ingest'])

# ── Tesseract OCR engine wiring ─────────────────────────────────────────────
try:
    import pytesseract
    _tesseract_path = os.environ.get('TESSERACT_CMD', r'C:\Program Files\Tesseract-OCR\tesseract.exe')
    if os.path.exists(_tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = _tesseract_path
        logger.info(f"Tesseract OCR engine found at: {_tesseract_path}")
    else:
        logger.warning(
            f"Tesseract OCR engine not found at '{_tesseract_path}'. "
            f"Image/scanned-PDF OCR will be skipped until it's installed "
            f"(https://github.com/UB-Mannheim/tesseract/wiki) and TESSERACT_CMD is set in .env."
        )
except ImportError:
    logger.warning("pytesseract not installed — OCR features disabled.")

# ── Configuration ──────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 1000 * 1024 * 1024
CHUNK_READ_SIZE = 1024 * 1024  # read the upload 1MB at a time instead of all at once
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'pptx', 'ppt', 'csv', 'txt', 'md', 'png', 'jpg', 'jpeg', 'webp', 'gif'}
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

MIN_PAGE_TEXT_CHARS = 20
MAX_OCR_PAGES_PER_DOCUMENT = 15


def _ocr_single_page(page, page_num: int) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image

        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img, lang='eng')
        if text.strip():
            logger.info(f"Per-page OCR: page {page_num} yielded {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"Per-page OCR failed on page {page_num}: {e}")
        return ""


def _extract_text_pdf_pymupdf(content: bytes) -> str | None:
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        if doc.is_encrypted:
            for pw in ['', 'password', '1234', 'admin', 'user', '12345']:
                try:
                    if doc.authenticate(pw):
                        logger.info(f"PyMuPDF: Decrypted PDF with password attempt")
                        break
                except Exception:
                    continue
            if doc.is_encrypted:
                logger.warning("PyMuPDF: Could not decrypt PDF with common passwords")
                doc.close()
                return None

        pages = []
        ocr_page_count = 0
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                text = page.get_text("text")
                if text and len(text.strip()) >= MIN_PAGE_TEXT_CHARS:
                    pages.append(text)
                    continue

                blocks = page.get_text("blocks")
                block_text = "\n".join(b[4] for b in blocks if b[6] == 0 and b[4].strip())
                if block_text and len(block_text.strip()) >= MIN_PAGE_TEXT_CHARS:
                    pages.append(block_text)
                    continue

                if ocr_page_count < MAX_OCR_PAGES_PER_DOCUMENT:
                    ocr_page_count += 1
                    ocr_text = _ocr_single_page(page, page_num)
                    pages.append(ocr_text or text or block_text or '')
                else:
                    pages.append(text or block_text or '')
            except Exception as e:
                logger.warning(f"PyMuPDF page {page_num} extraction failed: {e}")
                pages.append('')
        doc.close()
        result = '\n\n'.join(pages)
        if result.strip():
            logger.info(
                f"PyMuPDF: Extracted {len(result)} chars from {len(pages)} pages "
                f"({ocr_page_count} page(s) needed per-page OCR)"
            )
        return result
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed, falling back to pypdf")
        return None
    except Exception as e:
        logger.error(f"PyMuPDF extraction failed: {e}")
        return None


def _extract_text_pdf_pypdf(content: bytes) -> str | None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            decrypted = False
            for pw in ['', 'password', '1234', 'admin', 'user', '12345']:
                try:
                    result = reader.decrypt(pw)
                    if result:
                        decrypted = True
                        logger.info(f"pypdf: Decrypted PDF successfully")
                        break
                except Exception:
                    continue
            if not decrypted:
                logger.warning("pypdf: Could not decrypt PDF")
                return None
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or '')
            except Exception:
                pages.append('')
        result = '\n\n'.join(pages)
        if result.strip():
            logger.info(f"pypdf: Extracted {len(result)} chars from {len(pages)} pages")
        return result
    except ImportError:
        logger.warning("pypdf not installed, falling back to PyPDF2")
        return None
    except Exception as e:
        error_msg = str(e).lower()
        if 'pycryptodome' in error_msg or 'aes' in error_msg or 'crypto' in error_msg:
            logger.warning(f"pypdf: Crypto dependency issue ({e}), will try other extractors")
        else:
            logger.error(f"pypdf extraction failed: {e}")
        return None


def _extract_text_pdf_pypdf2(content: bytes) -> str | None:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or '')
            except Exception:
                pages.append('')
        result = '\n\n'.join(pages)
        if result.strip():
            logger.info(f"PyPDF2: Extracted {len(result)} chars from {len(pages)} pages")
        return result
    except Exception as e:
        error_msg = str(e).lower()
        if 'pycryptodome' in error_msg or 'aes' in error_msg or 'crypto' in error_msg:
            logger.warning(f"PyPDF2: Crypto dependency issue ({e}), will try OCR")
        else:
            logger.error(f"PyPDF2 extraction failed: {e}")
        return None


def _ocr_extract_text(content: bytes) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image

        doc = fitz.open(stream=content, filetype="pdf")
        text_parts = []
        max_pages = min(len(doc), 10)

        for page_num in range(max_pages):
            try:
                page = doc[page_num]
                mat = fitz.Matrix(300 / 72, 300 / 72)
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                text = pytesseract.image_to_string(img, lang='eng')
                if text.strip():
                    text_parts.append(text)
            except Exception as e:
                logger.warning(f"OCR page {page_num} failed: {e}")
        doc.close()
        result = '\n\n'.join(text_parts)
        if result.strip():
            logger.info(f"OCR: Extracted {len(result)} chars from {max_pages} pages")
        return result
    except ImportError:
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            images = convert_from_bytes(content, dpi=300, first_page=1, last_page=5)
            text_parts = []
            for img in images:
                try:
                    text = pytesseract.image_to_string(img, lang='eng')
                    if text.strip():
                        text_parts.append(text)
                except Exception as e:
                    logger.warning(f"OCR page failed: {e}")
            return '\n\n'.join(text_parts)
        except ImportError:
            logger.warning("OCR deps not installed (fitz/pdf2image/pytesseract)")
            return ""
        except Exception as e:
            logger.error(f"OCR extraction failed (pdf2image): {e}")
            return ""
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        return ""


def extract_text_pdf(content: bytes) -> str:
    strategies = [
        ("PyMuPDF", _extract_text_pdf_pymupdf),
        ("pypdf", _extract_text_pdf_pypdf),
        ("PyPDF2", _extract_text_pdf_pypdf2),
    ]
    errors = []
    for name, func in strategies:
        try:
            text = func(content)
            if text and text.strip():
                logger.info(f"PDF extraction succeeded with {name}")
                return text
            if text is not None:
                errors.append(f"{name}: returned empty text")
            else:
                errors.append(f"{name}: returned None")
        except Exception as e:
            errors.append(f"{name}: {e}")

    logger.info("All text extractors returned empty, trying whole-document OCR...")
    ocr_text = _ocr_extract_text(content)
    if ocr_text and ocr_text.strip():
        logger.info("PDF extraction succeeded with whole-document OCR fallback")
        return ocr_text

    for err in errors:
        logger.warning(f"PDF extraction attempt: {err}")
    logger.error("All PDF extraction strategies failed")
    return ""


def extract_text_docx(content: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text]
        return '\n'.join(paragraphs)
    except ImportError:
        logger.warning("python-docx not installed, using zipfile fallback")
    except Exception as e:
        logger.warning(f"python-docx failed: {e}")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml_content = z.read('word/document.xml')
            root = ET.fromstring(xml_content)
            texts = []
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            for p in root.findall('.//w:p', ns):
                p_text = "".join(t.text for t in p.findall('.//w:t', ns) if t.text)
                if p_text:
                    texts.append(p_text)
            return "\n".join(texts)
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def extract_text_pptx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            slide_texts = []
            ns = {
                'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
                'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
            }
            for name in sorted(z.namelist()):
                if name.startswith('ppt/slides/slide') and name.endswith('.xml'):
                    xml_content = z.read(name)
                    root = ET.fromstring(xml_content)
                    texts = [t.text for t in root.findall('.//a:t', ns) if t.text]
                    if texts:
                        slide_texts.append(' '.join(texts))
            return '\n\n'.join(slide_texts)
    except Exception as e:
        logger.error(f"Error reading PPTX: {e}")
        return ""


def extract_text_csv(content: bytes) -> str:
    try:
        text = content.decode('utf-8', errors='ignore')
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""
        headers = rows[0]
        result = []
        for i, row in enumerate(rows[1:], 1):
            row_str = ", ".join(
                f"{headers[j]}: {val}" for j, val in enumerate(row) if j < len(headers) and val
            )
            if row_str:
                result.append(f"Row {i}: {row_str}")
        return "\n".join(result)
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return ""


def extract_text_image(content: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(img, lang='eng')
        return text
    except ImportError:
        logger.warning("OCR deps not installed for image text extraction")
        return ""
    except Exception as e:
        logger.warning(f"Image OCR failed: {e}")
        return ""


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text or not text.strip():
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += (chunk_size - overlap)
        if start >= text_len:
            break
    return chunks


_indexing_progress: dict[str, dict] = {}


def _update_progress(doc_id: str, **kwargs):
    if doc_id not in _indexing_progress:
        _indexing_progress[doc_id] = {
            'status': 'pending', 'total_chunks': 0, 'indexed_chunks': 0,
            'errors': 0, 'stage': 'queued', 'progress_pct': 0,
        }
    _indexing_progress[doc_id].update(kwargs)
    _indexing_progress[doc_id]['progress_pct'] = (
        _indexing_progress[doc_id]['indexed_chunks'] /
        max(_indexing_progress[doc_id]['total_chunks'], 1)
    ) * 100


async def _index_document_background(
    doc_id: str, brand: str, filename: str, text: str,
    chunks: list[str], file_size: int, file_type: str
):
    _update_progress(doc_id, status='indexing', stage='extracting', total_chunks=len(chunks))
    indexed_count = 0
    errors = []
    total_start = _time.time()
    _update_progress(doc_id, stage='embedding')

    for idx, chunk in enumerate(chunks):
        try:
            embedding_vec = generate_embedding(chunk)
            if not embedding_vec:
                raise RuntimeError('Embedding returned empty vector')
            store_chunk_vector(doc_id, idx, chunk, embedding_vec)
            chroma_store.upsert_chunk(
                brand_key=brand, document_id=doc_id, doc_title=filename,
                chunk_index=idx, chunk_text=chunk, embedding=embedding_vec,
            )
            indexed_count += 1
        except Exception as e:
            errors.append({"chunk_index": idx, "error": str(e)})
            logger.error(f"Indexing chunk #{idx} failed: {e}")
        _update_progress(doc_id, indexed_chunks=indexed_count, errors=len(errors),
                         progress_pct=(indexed_count / max(len(chunks), 1)) * 100)

    total_elapsed = _time.time() - total_start
    status = 'completed' if indexed_count == len(chunks) else 'partial'
    try:
        update_document_status(doc_id, status)
    except Exception as e:
        logger.warning(f"Failed to update document status: {e}")
    _update_progress(doc_id, status=status, stage='done',
                     progress_pct=100 if status == 'completed' else 0,
                     elapsed_s=round(total_elapsed, 2))
    invalidate_brand_cache(brand)
    try:
        from core.db import create_notification
        create_notification(
            'file_indexed',
            f'Indexed {indexed_count}/{len(chunks)} chunks for brand {brand} ({filename})',
            json.dumps({"brand": brand, "document_id": doc_id, "errors": len(errors),
                        "elapsed_s": round(total_elapsed, 2)})
        )
    except Exception as e:
        logger.warning(f"Notification failed: {e}")
    logger.info(f"Indexing complete: {filename} -> {indexed_count}/{len(chunks)} chunks in {total_elapsed:.2f}s")


# ── Upload Endpoint ────────────────────────────────────────────────────────
@router.post('/upload')
async def upload_file(file: UploadFile = File(...), brand: str = Form(...)):
    """Upload a file. Reads the body in 1MB chunks (rather than one big
    file.read()) so very large uploads don't blow past what the ASGI/
    multipart layer can buffer in one go, and logs how long the read itself
    took so slow transfers are visible in the terminal."""
    brand = (brand or '').strip()
    if not brand:
        raise HTTPException(status_code=400, detail="Brand is required")
    filename = file.filename or 'unknown'
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    logger.info(f"Upload: filename='{filename}' brand='{brand}' ext='{ext}'")

    read_start = _time.time()
    chunks_buf = []
    total_read = 0
    try:
        while True:
            piece = await file.read(CHUNK_READ_SIZE)
            if not piece:
                break
            total_read += len(piece)
            if total_read > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large ({total_read/(1024*1024):.1f}MB). Max {MAX_FILE_SIZE_BYTES/(1024*1024):.0f}MB",
                )
            chunks_buf.append(piece)
    except HTTPException:
        raise
    except Exception as read_err:
        logger.error(f"Error reading upload body for '{filename}': {read_err}")
        raise HTTPException(
            status_code=400,
            detail="The upload was interrupted or the request body could not be read. Try again — for very large files, a stable connection matters.",
        )
    content = b"".join(chunks_buf)
    logger.info(f"Read {total_read/(1024*1024):.1f}MB for '{filename}' in {_time.time()-read_start:.2f}s")

    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    file_size = len(content)

    extract_start = _time.time()
    text = ''
    try:
        if ext == 'pdf':
            text = extract_text_pdf(content)
        elif ext in ('docx', 'doc'):
            text = extract_text_docx(content)
        elif ext in ('pptx', 'ppt'):
            text = extract_text_pptx(content)
        elif ext == 'csv':
            text = extract_text_csv(content)
        elif ext in ('md',):
            text = content.decode('utf-8', errors='ignore')
        elif ext in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            text = extract_text_image(content)
            if not text:
                text = f"[Image file: {filename}]"
        else:
            text = content.decode('utf-8', errors='ignore')
    except Exception as extract_err:
        logger.error(f"Error during file text extraction: {extract_err}")
        raise HTTPException(
            status_code=422,
            detail="Could not read file content. The file might be corrupted, password-protected, or formatted incorrectly."
        )

    logger.info(f"Extraction: {len(text)} chars in {_time.time()-extract_start:.3f}s")
    if not text.strip():
        if ext in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            text = f"[Image file: {filename}]"
        else:
            raise HTTPException(status_code=400, detail="Document appears empty or contains no extractable text.")

    chunks = chunk_text(text)
    logger.info(f"Chunking: {len(chunks)} chunks")
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks created from document")

    type_map = {'pdf': 'pdf', 'docx': 'docx', 'doc': 'docx', 'pptx': 'pptx', 'ppt': 'pptx',
                'csv': 'csv', 'txt': 'txt', 'md': 'md', 'png': 'image', 'jpg': 'image',
                'jpeg': 'image', 'webp': 'image', 'gif': 'image'}
    file_type = type_map.get(ext, 'txt')

    doc = create_document(brand_key=brand, filename=filename, content=text,
                          size=file_size, file_type=file_type, folder='uploads', status='processing')
    doc_id = doc['id']
    _indexing_progress[doc_id] = {'status': 'processing', 'total_chunks': len(chunks),
                                  'indexed_chunks': 0, 'errors': 0, 'stage': 'queued',
                                  'progress_pct': 0, 'filename': filename, 'brand': brand}

    asyncio.create_task(_index_document_background(
        doc_id=doc_id, brand=brand, filename=filename, text=text,
        chunks=chunks, file_size=file_size, file_type=file_type
    ))

    return {
        'id': doc_id, 'filename': filename, 'brand': brand,
        'file_size': file_size, 'content_size': len(text),
        'chunks_created': len(chunks), 'status': 'processing',
        'message': 'File uploaded. Indexing in progress.',
    }


@router.get('/progress/{doc_id}')
def get_index_progress(doc_id: str):
    progress = _indexing_progress.get(doc_id)
    if not progress:
        doc = get_document(doc_id)
        if doc:
            return {'id': doc_id, 'status': doc.get('status', 'completed'),
                    'stage': 'done', 'progress_pct': 100,
                    'total_chunks': 0, 'indexed_chunks': 0, 'errors': 0}
        raise HTTPException(status_code=404, detail="Document not found")
    return {'id': doc_id, **progress}


@router.get('/summary')
def upload_summary():
    return get_upload_summary()


@router.get('/files')
def uploaded_files(brand: str | None = Query(None)):
    return {'files': get_uploaded_files(brand)}


@router.delete('/files')
def delete_uploaded_file(file_id: str = Query(...)):
    doc = get_document(file_id)
    if doc:
        invalidate_brand_cache(doc.get('brand_key', ''))
    delete_document(file_id)
    _indexing_progress.pop(file_id, None)
    return {'id': file_id, 'status': 'deleted', 'summary': get_upload_summary()}


@router.put('/files/{file_id}')
def rename_uploaded_file(file_id: str, new_title: str = Form(...)):
    doc = rename_document(file_id, new_title)
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    return {'document': doc}


@router.get('/files/{file_id}')
def get_file_metadata(file_id: str):
    doc = get_document(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    return {'document': doc}


@router.get('/files/{file_id}/preview')
def preview_uploaded_file(file_id: str):
    doc = get_document(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    content = doc.get('content', '')
    file_type = doc.get('type', 'txt')
    filename = doc.get('filename', 'document')
    status = doc.get('status', 'unknown')
    uploaded_at = doc.get('uploaded_at', '')
    file_size = doc.get('size', 0)

    if file_type == 'image' and content and content.startswith('['):
        pass

    preview_content = content[:50000] if content else ''

    return PlainTextResponse(
        preview_content,
        media_type='text/plain',
        headers={
            'X-File-Name': filename,
            'X-File-Type': file_type,
            'X-File-Size': str(file_size),
            'X-File-Status': status,
            'X-File-Uploaded-At': uploaded_at,
            'X-File-Brand': doc.get('brand_key', ''),
        }
    )


@router.get('/files/{file_id}/preview/html')
def preview_uploaded_file_html(file_id: str):
    from fastapi.responses import HTMLResponse
    doc = get_document(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    content = doc.get('content', '')
    file_type = doc.get('type', 'txt')
    filename = doc.get('filename', 'document')
    status = doc.get('status', 'unknown')
    uploaded_at = doc.get('uploaded_at', '')
    file_size = doc.get('size', 0)

    preview_text = content[:50000] if content else ''

    import html
    escaped = html.escape(preview_text)
    html_content = escaped.replace('\n', '<br>')

    html_response = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(filename)} - Preview</title>
<style>
  body {{ background: #0d0d0f; color: #f0eff8; font-family: 'Inter', sans-serif; padding: 24px; margin: 0; }}
  .meta {{ display: flex; gap: 20px; padding: 12px 16px; background: #1a1a20; border-radius: 8px; margin-bottom: 16px; font-size: 12px; color: #8888a8; }}
  .meta span strong {{ color: #f0eff8; }}
  .content {{ background: #111115; border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 20px; line-height: 1.7; font-size: 14px; white-space: pre-wrap; word-wrap: break-word; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge.completed {{ background: rgba(43, 207, 160, 0.15); color: #2bcfa0; }}
  .badge.processing {{ background: rgba(240, 160, 48, 0.15); color: #f0a030; }}
  .badge.error {{ background: rgba(240, 80, 80, 0.15); color: #f05050; }}
</style>
</head>
<body>
  <div class="meta">
    <span><strong>File:</strong> {html.escape(filename)}</span>
    <span><strong>Type:</strong> {html.escape(file_type)}</span>
    <span><strong>Size:</strong> {file_size} bytes</span>
    <span><strong>Status:</strong> <span class="badge {status}">{html.escape(status)}</span></span>
    <span><strong>Uploaded:</strong> {html.escape(uploaded_at)}</span>
  </div>
  <div class="content">{html_content}</div>
</body>
</html>"""
    return HTMLResponse(content=html_response)


@router.get('/files/{file_id}/download')
def download_uploaded_file(file_id: str):
    doc = get_document(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    content = doc.get('content', '')
    filename = doc.get('filename', file_id)
    return PlainTextResponse(
        content, media_type='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}.txt"'}
    )


@router.get('/vector-db')
def vector_db_summary():
    return {'collections': chroma_store.list_collections(), 'documents': get_upload_summary()}


@router.post('/reset')
def reset_uploads():
    _indexing_progress.clear()
    reset_uploaded_documents()
    return {'status': 'reset', 'summary': get_upload_summary()}