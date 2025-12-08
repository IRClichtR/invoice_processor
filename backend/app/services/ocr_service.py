import pytesseract
from PIL import Image
from typing import Dict, List, Any
import numpy as np
from app.core.config import settings


class OCRService:
    """Tesseract OCR service optimized for French and English text extraction"""

    def __init__(self):
        self.lang = settings.TESSERACT_LANG
        self.config = settings.TESSERACT_CONFIG

    def extract_text_with_details(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract text with positions and confidence scores using Tesseract
        Optimized for French and English invoice processing

        Args:
            image: PIL Image

        Returns:
            Dictionary containing:
            - full_text: Complete extracted text
            - word_data: Detailed word-level information including positions and confidence
            - average_confidence: Average confidence score across all words
        """
        # Get detailed OCR data with French and English support
        ocr_data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            config=self.config,
            output_type=pytesseract.Output.DICT
        )

        # Get full text
        full_text = pytesseract.image_to_string(
            image,
            lang=self.lang,
            config=self.config
        )

        # Process OCR data
        word_data = []
        n_boxes = len(ocr_data['text'])

        for i in range(n_boxes):
            # Filter out empty detections and low confidence results
            text = str(ocr_data['text'][i]).strip()
            confidence = int(ocr_data['conf'][i])

            if text and confidence > 0:
                word_info = {
                    'text': text,
                    'confidence': float(confidence),
                    'left': int(ocr_data['left'][i]),
                    'top': int(ocr_data['top'][i]),
                    'width': int(ocr_data['width'][i]),
                    'height': int(ocr_data['height'][i]),
                    'block_num': int(ocr_data['block_num'][i]),
                    'par_num': int(ocr_data['par_num'][i]),
                    'line_num': int(ocr_data['line_num'][i]),
                    'word_num': int(ocr_data['word_num'][i])
                }
                word_data.append(word_info)

        # Calculate average confidence
        if word_data:
            avg_confidence = sum(w['confidence'] for w in word_data) / len(word_data)
        else:
            avg_confidence = 0.0

        return {
            'full_text': full_text,
            'word_data': word_data,
            'average_confidence': avg_confidence,
            'total_words': len(word_data)
        }

    def extract_from_multiple_images(self, images: List[Image.Image]) -> List[Dict[str, Any]]:
        """
        Extract text from multiple images (pages)

        Args:
            images: List of PIL Images

        Returns:
            List of OCR results for each page
        """
        results = []
        for idx, image in enumerate(images):
            try:
                result = self.extract_text_with_details(image)
                result['page_number'] = idx + 1
                results.append(result)
            except Exception as e:
                results.append({
                    'page_number': idx + 1,
                    'error': str(e),
                    'full_text': '',
                    'word_data': [],
                    'average_confidence': 0.0,
                    'total_words': 0
                })

        return results

    def get_text_blocks(self, image: Image.Image) -> List[Dict[str, Any]]:
        """
        Extract text organized by blocks for better structure understanding

        Args:
            image: PIL Image

        Returns:
            List of text blocks with positions
        """
        ocr_data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            config=self.config,
            output_type=pytesseract.Output.DICT
        )

        blocks = {}
        n_boxes = len(ocr_data['text'])

        for i in range(n_boxes):
            text = str(ocr_data['text'][i]).strip()
            if text and int(ocr_data['conf'][i]) > 0:
                block_num = int(ocr_data['block_num'][i])

                if block_num not in blocks:
                    blocks[block_num] = {
                        'block_num': block_num,
                        'text': [],
                        'left': int(ocr_data['left'][i]),
                        'top': int(ocr_data['top'][i]),
                        'width': int(ocr_data['width'][i]),
                        'height': int(ocr_data['height'][i])
                    }

                blocks[block_num]['text'].append(text)

        # Convert to list and join text
        block_list = []
        for block in blocks.values():
            block['text'] = ' '.join(block['text'])
            block_list.append(block)

        return block_list
