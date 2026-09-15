"""Extract CV text with pdfplumber."""
import pdfplumber


def extract_text_from_pdf(pdf_path):
    """Return all PDF text, or an empty string on failure."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"[pdf_parser] Error reading {pdf_path}: {e}")
    return text.strip()
