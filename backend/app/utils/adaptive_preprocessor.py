import cv2
import numpy as np
from PIL import Image
from typing import Union, Tuple
from app.utils.image_preprocessor import ImagePreprocessor


class AdaptivePreprocessor:
    """
    Adaptive preprocessing that analyzes image quality first
    and applies only necessary enhancements
    """

    @staticmethod
    def assess_image_quality(image: np.ndarray) -> dict:
        """
        Assess various quality metrics of the image

        Args:
            image: OpenCV image (BGR format)

        Returns:
            Dictionary with quality metrics
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Calculate sharpness using Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # Calculate brightness (mean intensity)
        brightness = np.mean(gray)

        # Calculate contrast (standard deviation)
        contrast = np.std(gray)

        # Estimate noise level
        noise = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        noise_level = np.mean(np.abs(gray.astype(float) - noise.astype(float)))

        return {
            'sharpness': laplacian_var,
            'brightness': brightness,
            'contrast': contrast,
            'noise_level': noise_level,
            'is_sharp': laplacian_var > 100,  # Good sharpness
            'is_bright_enough': 50 < brightness < 200,  # Not too dark/bright
            'has_good_contrast': contrast > 30,  # Sufficient contrast
            'is_noisy': noise_level > 5  # Noticeable noise
        }

    @classmethod
    def smart_preprocess(cls, image: Union[Image.Image, np.ndarray]) -> Tuple[Image.Image, dict]:
        """
        Apply adaptive preprocessing based on image quality assessment

        Args:
            image: PIL Image or OpenCV image

        Returns:
            Tuple of (preprocessed PIL Image, processing report)
        """
        preprocessor = ImagePreprocessor()

        # Convert to OpenCV format if needed
        if isinstance(image, Image.Image):
            cv2_image = preprocessor.pil_to_cv2(image)
        else:
            cv2_image = image.copy()

        # Assess image quality
        quality = cls.assess_image_quality(cv2_image)

        report = {
            'quality_metrics': quality,
            'operations_applied': []
        }

        # Only apply preprocessing if needed
        processed = cv2_image.copy()

        # 1. Deskew only if image appears skewed (skip for most clean PDFs)
        # Most modern PDFs don't need deskewing
        # Skip this step entirely for digital PDFs
        # report['operations_applied'].append('skipped_deskew')

        # 2. Apply gentle CLAHE only if contrast is poor
        if not quality['has_good_contrast']:
            processed = preprocessor.apply_clahe(processed, clip_limit=1.2, tile_size=8)
            report['operations_applied'].append('gentle_clahe')
        else:
            report['operations_applied'].append('skipped_clahe')

        # 3. Apply light denoising only if image is noisy
        if quality['is_noisy']:
            processed = preprocessor.denoise(processed, strength=3)
            report['operations_applied'].append('light_denoise')
        else:
            report['operations_applied'].append('skipped_denoise')

        # 4. Skip binarization for high-quality PDFs
        # Binarization can lose information in color documents
        report['operations_applied'].append('skipped_binarization')

        # Convert back to PIL
        result_image = preprocessor.cv2_to_pil(processed)

        return result_image, report

    @classmethod
    def preprocess_for_ocr(cls, image: Union[Image.Image, np.ndarray], mode: str = 'adaptive') -> Tuple[Image.Image, dict]:
        """
        Main preprocessing method with different modes

        Args:
            image: Input image
            mode: 'adaptive', 'gentle', 'aggressive', 'handwritten', 'auto', or 'none'

        Returns:
            Tuple of (Preprocessed PIL Image, processing report)
        """
        preprocessor = ImagePreprocessor()
        report = {'mode': mode, 'operations': []}

        if mode == 'none':
            # Return original
            if isinstance(image, Image.Image):
                return image, report
            return preprocessor.cv2_to_pil(image), report

        elif mode == 'auto':
            # Auto-detect if handwritten and apply appropriate preprocessing
            if isinstance(image, Image.Image):
                cv2_image = preprocessor.pil_to_cv2(image)
            else:
                cv2_image = image.copy()

            is_handwritten, metrics = preprocessor.detect_handwritten(cv2_image)
            report['handwritten_detection'] = metrics
            report['is_handwritten'] = is_handwritten

            if is_handwritten:
                result, hw_report = preprocessor.preprocess_handwritten(cv2_image)
                report['operations'] = hw_report['operations_applied']
                report['rotation_angle'] = hw_report.get('rotation_angle', 0)
                return result, report
            else:
                # Fall back to adaptive for non-handwritten
                result, adapt_report = cls.smart_preprocess(cv2_image)
                report['operations'] = adapt_report['operations_applied']
                return result, report

        elif mode == 'handwritten':
            # Force handwritten preprocessing
            result, hw_report = preprocessor.preprocess_handwritten(image)
            report['operations'] = hw_report['operations_applied']
            report['rotation_angle'] = hw_report.get('rotation_angle', 0)
            report['blue_ink_detected'] = hw_report.get('blue_ink_detected', False)
            return result, report

        elif mode == 'adaptive':
            # Smart preprocessing based on quality assessment
            result, adapt_report = cls.smart_preprocess(image)
            report['operations'] = adapt_report['operations_applied']
            report['quality_metrics'] = adapt_report.get('quality_metrics', {})
            return result, report

        elif mode == 'gentle':
            # Gentle preprocessing for high-quality scans
            if isinstance(image, Image.Image):
                cv2_image = preprocessor.pil_to_cv2(image)
            else:
                cv2_image = image.copy()

            # Only gentle CLAHE
            processed = preprocessor.apply_clahe(cv2_image, clip_limit=1.2)
            report['operations'] = ['gentle_clahe']
            return preprocessor.cv2_to_pil(processed), report

        elif mode == 'aggressive':
            # Full preprocessing for poor quality scans
            result = preprocessor.preprocess(
                image,
                apply_deskew=True,
                apply_clahe_filter=True,
                apply_denoise_filter=True,
                apply_binarize=True
            )
            report['operations'] = ['deskew', 'clahe', 'denoise', 'binarize']
            return result, report

        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'auto', 'adaptive', 'gentle', 'aggressive', 'handwritten', or 'none'")
