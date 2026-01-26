"""
OCR Service - Extract text with spatial positions using Tesseract
"""

import os
import pytesseract
from PIL import Image
from typing import Dict, List, Any
import structlog
import time

from app.core.config import settings
from app.core.bundled_deps import get_tesseract_cmd, get_tessdata_prefix

# Configure bundled tesseract if running from PyInstaller build
_bundled_tesseract = get_tesseract_cmd()
if _bundled_tesseract:
    pytesseract.pytesseract.tesseract_cmd = _bundled_tesseract

_bundled_tessdata = get_tessdata_prefix()
if _bundled_tessdata:
    os.environ['TESSDATA_PREFIX'] = _bundled_tessdata

logger = structlog.get_logger(__name__)


class OCRService:
    """Tesseract OCR service for spatial text extraction"""

    def __init__(self, lang: str = "fra+eng"):
        self.lang = lang
        # Use threshold from config
        self.low_confidence_threshold = settings.OCR_LOW_CONFIDENCE_THRESHOLD

    def extract_spatial_text(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract text with normalized positions from image.

        Returns:
            {
                'full_text': str,
                'spatial_grid': str,  # Formatted for VLM context
                'words': List[Dict],  # Raw word data
                'confidence': {
                    'average': float,      # Average confidence (0-100)
                    'word_count': int,     # Total words detected
                    'low_conf_ratio': float,  # Ratio of low-confidence words
                    'is_low_quality': bool,   # True if below threshold
                }
            }
        """
        if image.mode != 'RGB':
            image = image.convert('RGB')

        width, height = image.size
        logger.info("Running Tesseract OCR", width=width, height=height, lang=self.lang)
        ocr_start = time.time()

        # Get word-level data with bounding boxes
        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            output_type=pytesseract.Output.DICT,
            config='--psm 6'  # Assume uniform block of text
        )

        words = []
        all_confidences = []  # Track all confidences for analysis

        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            conf = int(data['conf'][i])

            # Track confidence for non-empty text (even if low)
            if text and conf >= 0:
                all_confidences.append(conf)

            # Skip empty or very low-confidence words for extraction
            if not text or conf < 30:
                continue

            # Normalize positions to 0-1 range
            x = data['left'][i] / width
            y = data['top'][i] / height
            w = data['width'][i] / width
            h = data['height'][i] / height

            words.append({
                'text': text,
                'x': round(x, 3),
                'y': round(y, 3),
                'w': round(w, 3),
                'h': round(h, 3),
                'conf': conf
            })

        # Calculate confidence metrics
        confidence_metrics = self._calculate_confidence_metrics(all_confidences, words)

        # Build spatial grid string for VLM
        spatial_grid = self._build_spatial_grid(words)

        # Build full text
        full_text = pytesseract.image_to_string(image, lang=self.lang)

        ocr_time = time.time() - ocr_start
        logger.info(
            "OCR completed",
            word_count=len(words),
            text_length=len(full_text),
            avg_confidence=confidence_metrics['average'],
            is_low_quality=confidence_metrics['is_low_quality'],
            ocr_time_sec=round(ocr_time, 2)
        )

        return {
            'full_text': full_text.strip(),
            'spatial_grid': spatial_grid,
            'words': words,
            'confidence': confidence_metrics
        }

    def _calculate_confidence_metrics(
        self,
        all_confidences: List[int],
        words: List[Dict]
    ) -> Dict[str, Any]:
        """Calculate OCR confidence metrics"""
        if not all_confidences:
            return {
                'average': 0.0,
                'word_count': 0,
                'low_conf_ratio': 1.0,
                'is_low_quality': True
            }

        avg_confidence = sum(all_confidences) / len(all_confidences)
        low_conf_count = sum(1 for c in all_confidences if c < self.low_confidence_threshold)
        low_conf_ratio = low_conf_count / len(all_confidences)

        return {
            'average': round(avg_confidence, 2),
            'word_count': len(words),
            'low_conf_ratio': round(low_conf_ratio, 3),
            'is_low_quality': avg_confidence < self.low_confidence_threshold
        }

    def _build_spatial_grid(self, words: List[Dict]) -> str:
        """
        Build a spatial text grid string for VLM context.

        Format:
        [y_pos] "text" "text" "text"
        [y_pos] "text" "text"

        Groups words by approximate Y position (line).
        """
        if not words:
            return ""

        # Sort by Y position, then X
        sorted_words = sorted(words, key=lambda w: (w['y'], w['x']))

        lines = []
        current_line = []
        current_y = -1
        y_tolerance = 0.015  # 1.5% of image height

        for word in sorted_words:
            if current_y < 0 or abs(word['y'] - current_y) <= y_tolerance:
                current_line.append(word)
                if current_y < 0:
                    current_y = word['y']
            else:
                # New line
                if current_line:
                    lines.append((current_y, current_line))
                current_line = [word]
                current_y = word['y']

        # Add last line
        if current_line:
            lines.append((current_y, current_line))

        # Format as spatial grid
        grid_lines = []
        for y_pos, line_words in lines:
            # Sort line by X position
            line_words_sorted = sorted(line_words, key=lambda w: w['x'])
            texts = [f'"{w["text"]}"' for w in line_words_sorted]
            grid_lines.append(f"[{y_pos:.2f}] {' '.join(texts)}")

        return "\n".join(grid_lines)
