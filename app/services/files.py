"""업로드 파일에서 텍스트 추출 → 글자 수 계산"""
import io

from fastapi import HTTPException

SUPPORTED = (".txt", ".md", ".csv", ".docx", ".pdf")


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith((".txt", ".md", ".csv")):
            for enc in ("utf-8-sig", "cp949"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="ignore")
        if name.endswith(".docx"):
            from docx import Document

            return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    except Exception as e:  # 손상된 파일 등
        raise HTTPException(422, f"파일에서 텍스트를 읽지 못했습니다: {e}")
    raise HTTPException(415, f"지원하지 않는 형식입니다. ({', '.join(SUPPORTED)})")
