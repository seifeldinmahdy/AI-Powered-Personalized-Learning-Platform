"""PDF loading and chunking utilities."""

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter


def load_and_chunk_pdf(
    pdf_path: str | Path,
    chunk_size: int = 1000,
    chunk_overlap: int = 100
) -> list[str]:
    """
    Load a PDF file and split it into text chunks.
    
    Args:
        pdf_path: Path to the PDF file
        chunk_size: Maximum size of each chunk in characters
        chunk_overlap: Number of overlapping characters between chunks
        
    Returns:
        List of text chunks from the PDF
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    # Load PDF pages
    loader = PyPDFLoader(str(pdf_path))
    pages = loader.load()
    
    # Combine all page content
    full_text = "\n".join(page.page_content for page in pages)
    
    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    
    chunks = splitter.split_text(full_text)
    
    # Filter out very short chunks (likely artifacts)
    chunks = [c.strip() for c in chunks if len(c.strip()) > 50]
    
    return chunks
