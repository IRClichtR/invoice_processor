# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Image Quality Analyzer Service

Analyzes image quality and OCR confidence to determine if Claude Vision
should be used for processing low-quality or handwritten documents.
"""

from enum import Enum
from typing import Dict, Any, Optional
from PIL import Image
import numpy as np
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class DocumentQuality(str, Enum):
    """Document quality classification"""
    GOOD = "good"
    LOW_QUALITY = "low_quality"
    HANDWRITTEN = "handwritten"
    EXTREMELY_LOW_QUALITY = "extremely_low_quality"


class ImageAnalyzer:
    """
    Analyzes document images to assess quality and recommend processing path.

    Multi-step workflow:
    1. Analyze image properties (blur, contrast, noise)
    2. Assess OCR confidence from OCR service results
    3. Detect potential handwriting
    4. Recommend processing path (standard vs Claude Vision)
    """

    # Thresholds - use config value for OCR confidence
    EXTREMELY_LOW_THRESHOLD = 25.0   # Below this, extremely low quality
    HANDWRITING_VARIANCE_THRESHOLD = 0.15  # High variance in word positions suggests handwriting

    def __init__(self):
        # Use threshold from config
        self.ocr_confidence_threshold = settings.OCR_LOW_CONFIDENCE_THRESHOLD

    def analyze(
        self,
        image: Image.Image,
        ocr_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze image quality and OCR results.

        Args:
            image: PIL Image to analyze
            ocr_result: Result from OCRService.extract_spatial_text()

        Returns:
            {
                'quality': DocumentQuality,
                'ocr_confidence': float,
                'is_low_quality': bool,
                'is_handwritten': bool,
                'requires_claude_vision': bool,
                'recommendation': str,
                'details': {
                    'blur_score': float,
                    'contrast_score': float,
                    'word_count': int,
                    'low_conf_ratio': float
                }
            }
        """
        logger.info("Analyzing image quality")

        # Get OCR confidence metrics
        confidence = ocr_result.get('confidence', {})
        ocr_avg = confidence.get('average', 0.0)
        word_count = confidence.get('word_count', 0)
        low_conf_ratio = confidence.get('low_conf_ratio', 1.0)

        # Analyze image properties
        image_stats = self._analyze_image_properties(image)

        # Detect potential handwriting
        is_handwritten = self._detect_handwriting(ocr_result.get('words', []), image_stats)

        # Determine quality classification
        quality = self._classify_quality(ocr_avg, is_handwritten, word_count)

        # Determine if Claude Vision is recommended
        requires_claude = quality in [
            DocumentQuality.LOW_QUALITY,
            DocumentQuality.HANDWRITTEN,
            DocumentQuality.EXTREMELY_LOW_QUALITY
        ]

        # Generate recommendation message
        recommendation = self._generate_recommendation(quality, ocr_avg, is_handwritten)

        result = {
            'quality': quality.value,
            'ocr_confidence': ocr_avg,
            'is_low_quality': ocr_avg < self.ocr_confidence_threshold,
            'is_handwritten': is_handwritten,
            'requires_claude_vision': requires_claude,
            'recommendation': recommendation,
            'details': {
                'blur_score': image_stats.get('blur_score', 0.0),
                'contrast_score': image_stats.get('contrast_score', 0.0),
                'word_count': word_count,
                'low_conf_ratio': low_conf_ratio
            }
        }

        logger.info(
            "Image analysis complete",
            quality=quality.value,
            ocr_confidence=ocr_avg,
            requires_claude=requires_claude
        )

        return result

    def _analyze_image_properties(self, image: Image.Image) -> Dict[str, float]:
        """Analyze image properties like blur and contrast"""
        try:
            # Convert to grayscale for analysis
            gray = image.convert('L')
            img_array = np.array(gray)

            # Calculate Laplacian variance (blur detection)
            # Higher variance = sharper image
            laplacian = np.array([
                [0, 1, 0],
                [1, -4, 1],
                [0, 1, 0]
            ])
            from scipy.ndimage import convolve
            lap_result = convolve(img_array.astype(float), laplacian)
            blur_score = np.var(lap_result)

            # Normalize blur score (0-100 scale)
            blur_score = min(100, blur_score / 100)

            # Calculate contrast (standard deviation of pixel values)
            contrast_score = np.std(img_array)
            # Normalize to 0-100 scale
            contrast_score = min(100, contrast_score / 2.55 * 100 / 50)

            return {
                'blur_score': round(blur_score, 2),
                'contrast_score': round(contrast_score, 2)
            }
        except ImportError:
            # scipy not available, return neutral scores
            logger.warning("scipy not available for image analysis, using defaults")
            return {
                'blur_score': 50.0,
                'contrast_score': 50.0
            }
        except Exception as e:
            logger.error("Error analyzing image properties", error=str(e))
            return {
                'blur_score': 50.0,
                'contrast_score': 50.0
            }

    def _detect_handwriting(
        self,
        words: list,
        image_stats: Dict[str, float]
    ) -> bool:
        """
        Detect if document appears to be handwritten.

        Handwriting indicators:
        - Irregular word spacing and alignment
        - High variance in word heights
        - Low OCR confidence with readable text present
        """
        if not words or len(words) < 5:
            return False

        try:
            # Check variance in word heights (handwriting has irregular heights)
            heights = [w['h'] for w in words]
            height_variance = np.var(heights) if heights else 0

            # Check variance in y-positions within lines (handwriting is less aligned)
            y_positions = [w['y'] for w in words]
            y_variance = np.var(y_positions) if y_positions else 0

            # Handwriting typically has higher variance in both
            is_irregular = height_variance > 0.001 and y_variance > self.HANDWRITING_VARIANCE_THRESHOLD

            # Also check if many words have medium confidence (30-60)
            # Handwriting often has partial recognition
            medium_conf_count = sum(1 for w in words if 30 <= w.get('conf', 0) <= 60)
            medium_conf_ratio = medium_conf_count / len(words)

            return is_irregular or medium_conf_ratio > 0.5

        except Exception as e:
            logger.error("Error detecting handwriting", error=str(e))
            return False

    def _classify_quality(
        self,
        ocr_confidence: float,
        is_handwritten: bool,
        word_count: int
    ) -> DocumentQuality:
        """Classify document quality based on analysis"""
        if is_handwritten:
            return DocumentQuality.HANDWRITTEN

        if ocr_confidence < self.EXTREMELY_LOW_THRESHOLD or word_count < 3:
            return DocumentQuality.EXTREMELY_LOW_QUALITY

        if ocr_confidence < self.ocr_confidence_threshold:
            return DocumentQuality.LOW_QUALITY

        return DocumentQuality.GOOD

    def _generate_recommendation(
        self,
        quality: DocumentQuality,
        ocr_confidence: float,
        is_handwritten: bool
    ) -> str:
        """Generate human-readable recommendation"""
        if quality == DocumentQuality.GOOD:
            return "Document quality is good. Standard processing recommended."

        if quality == DocumentQuality.HANDWRITTEN:
            return (
                "Document appears to be handwritten. "
                "Claude Vision is recommended for accurate text extraction."
            )

        if quality == DocumentQuality.EXTREMELY_LOW_QUALITY:
            return (
                f"Document quality is extremely low (OCR confidence: {ocr_confidence:.1f}%). "
                "Claude Vision is strongly recommended for this document."
            )

        # LOW_QUALITY
        return (
            f"Document quality is low (OCR confidence: {ocr_confidence:.1f}%). "
            "Claude Vision is recommended for better accuracy."
        )
