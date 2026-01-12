import cv2
import numpy as np
from PIL import Image
from typing import Union, Tuple


class ImagePreprocessor:
    """Image preprocessing for OCR optimization"""

    @staticmethod
    def pil_to_cv2(image: Image.Image) -> np.ndarray:
        """Convert PIL Image to OpenCV format"""
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def cv2_to_pil(image: np.ndarray) -> Image.Image:
        """Convert OpenCV image to PIL format"""
        return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    @staticmethod
    def deskew(image: np.ndarray, angle_threshold: float = 0.5) -> np.ndarray:
        """
        Deskew image by detecting rotation angle
        Only applies rotation if angle is significant

        Args:
            image: OpenCV image (BGR format)
            angle_threshold: Minimum angle to trigger rotation (degrees)

        Returns:
            Deskewed image
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Apply threshold to get binary image
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        # Find coordinates of all non-zero points
        coords = np.column_stack(np.where(thresh > 0))

        if len(coords) < 100:
            # Not enough points to determine skew
            return image

        # Find minimum area rectangle
        angle = cv2.minAreaRect(coords)[-1]

        # Adjust angle
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Only rotate if angle is significant
        if abs(angle) < angle_threshold:
            return image

        # Rotate image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)

        return rotated

    @staticmethod
    def apply_clahe(image: np.ndarray, clip_limit: float = 1.5, tile_size: int = 8) -> np.ndarray:
        """
        Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        Uses gentler settings to avoid over-enhancement

        Args:
            image: OpenCV image (BGR format)
            clip_limit: Threshold for contrast limiting (reduced from 2.0 to 1.5)
            tile_size: Size of grid for histogram equalization

        Returns:
            Contrast enhanced image
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Apply CLAHE to L channel with gentler settings
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
        cl = clahe.apply(l)

        # Merge channels
        limg = cv2.merge((cl, a, b))

        # Convert back to BGR
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        return enhanced

    @staticmethod
    def denoise(image: np.ndarray, strength: int = 5) -> np.ndarray:
        """
        Apply denoising to image
        Uses gentler strength to preserve details

        Args:
            image: OpenCV image (BGR format)
            strength: Denoising strength (reduced from 10 to 5)

        Returns:
            Denoised image
        """
        return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)

    @staticmethod
    def binarize(image: np.ndarray, method: str = "otsu") -> np.ndarray:
        """
        Apply binarization to image

        Args:
            image: OpenCV image (BGR format)
            method: Binarization method ("otsu" or "adaptive")

        Returns:
            Binarized image
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        if method == "otsu":
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif method == "adaptive":
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 11, 2)
        else:
            raise ValueError(f"Unknown binarization method: {method}")

        # Convert back to BGR for consistency
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def detect_handwritten(image: np.ndarray) -> Tuple[bool, dict]:
        """
        Detect if document appears to be handwritten based on stroke analysis.

        Args:
            image: OpenCV image (BGR format)

        Returns:
            Tuple of (is_handwritten, metrics_dict)
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Edge detection to find strokes
        edges = cv2.Canny(gray, 50, 150)

        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) < 10:
            return False, {'contour_count': len(contours), 'reason': 'too_few_contours'}

        # Analyze contour characteristics
        stroke_widths = []
        irregularities = []

        for contour in contours:
            if len(contour) < 5:
                continue

            # Fit ellipse to measure stroke characteristics
            try:
                ellipse = cv2.fitEllipse(contour)
                axes = ellipse[1]
                if axes[0] > 0:
                    aspect_ratio = axes[1] / axes[0]
                    irregularities.append(aspect_ratio)
            except cv2.error:
                continue

            # Calculate arc length vs area ratio (handwriting has higher ratios)
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            if area > 0:
                compactness = (perimeter ** 2) / (4 * np.pi * area)
                stroke_widths.append(compactness)

        if not stroke_widths:
            return False, {'reason': 'no_valid_strokes'}

        # Handwritten text has more variation in stroke characteristics
        stroke_variation = np.std(stroke_widths) if len(stroke_widths) > 1 else 0
        avg_compactness = np.mean(stroke_widths)

        # Check for blue ink presence
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv, (100, 50, 50), (130, 255, 255))
        blue_ratio = np.sum(blue_mask > 0) / blue_mask.size

        metrics = {
            'stroke_variation': stroke_variation,
            'avg_compactness': avg_compactness,
            'contour_count': len(contours),
            'blue_ink_ratio': blue_ratio,
            'irregularity_std': np.std(irregularities) if irregularities else 0
        }

        # Heuristics for handwritten detection
        is_handwritten = (
            (stroke_variation > 2.0 and avg_compactness > 1.5) or
            (blue_ratio > 0.001) or  # Blue ink detected
            (metrics['irregularity_std'] > 0.5 and len(contours) > 50)
        )

        return is_handwritten, metrics

    @staticmethod
    def enhance_blue_ink(image: np.ndarray) -> np.ndarray:
        """
        Enhance blue ink visibility for better OCR on handwritten documents.

        Args:
            image: OpenCV image (BGR format)

        Returns:
            Image with enhanced blue ink
        """
        # Convert to HSV for better color isolation
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Blue ink range in HSV (covering light to dark blue)
        lower_blue = np.array([90, 30, 30])
        upper_blue = np.array([130, 255, 255])

        # Create mask for blue regions
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # Check if there's significant blue content
        blue_ratio = np.sum(blue_mask > 0) / blue_mask.size

        if blue_ratio < 0.0005:  # Less than 0.05% blue, skip enhancement
            return image

        # Convert to LAB for better manipulation
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Enhance the blue channel (negative b values in LAB)
        # Darken blue regions in the L channel for better contrast
        blue_mask_dilated = cv2.dilate(blue_mask, np.ones((3, 3), np.uint8), iterations=1)

        # Darken blue ink areas
        l_enhanced = l.copy()
        l_enhanced[blue_mask_dilated > 0] = np.clip(
            l[blue_mask_dilated > 0].astype(np.int16) - 40, 0, 255
        ).astype(np.uint8)

        # Increase contrast in blue regions
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_enhanced)

        # Merge back
        enhanced_lab = cv2.merge([l_enhanced, a, b])
        enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

        return enhanced

    @staticmethod
    def fix_rotation(image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Detect and fix image rotation using multiple methods.

        Args:
            image: OpenCV image (BGR format)

        Returns:
            Tuple of (rotated image, rotation angle applied)
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Method 1: Use Hough Line Transform for dominant line detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=100, maxLineGap=10)

        angles = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if x2 - x1 != 0:
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    # Normalize angle to -45 to 45 range
                    if angle > 45:
                        angle -= 90
                    elif angle < -45:
                        angle += 90
                    angles.append(angle)

        # Method 2: Use minAreaRect on text contours
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))

        if len(coords) > 100:
            rect_angle = cv2.minAreaRect(coords)[-1]
            if rect_angle < -45:
                rect_angle = -(90 + rect_angle)
            else:
                rect_angle = -rect_angle
            angles.append(rect_angle)

        if not angles:
            return image, 0.0

        # Use median angle to reduce outlier impact
        rotation_angle = np.median(angles)

        # Only rotate if angle is significant but not extreme
        if abs(rotation_angle) < 0.3 or abs(rotation_angle) > 45:
            return image, 0.0

        # Apply rotation
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)

        # Calculate new image dimensions to avoid clipping
        cos = abs(np.cos(np.radians(rotation_angle)))
        sin = abs(np.sin(np.radians(rotation_angle)))
        new_w = int(h * sin + w * cos)
        new_h = int(h * cos + w * sin)

        # Adjust rotation matrix
        M = cv2.getRotationMatrix2D(center, rotation_angle, 1.0)
        M[0, 2] += (new_w - w) / 2
        M[1, 2] += (new_h - h) / 2

        rotated = cv2.warpAffine(image, M, (new_w, new_h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)

        return rotated, rotation_angle

    @staticmethod
    def enhance_handwritten(image: np.ndarray) -> np.ndarray:
        """
        Apply comprehensive enhancement for handwritten documents.

        Args:
            image: OpenCV image (BGR format)

        Returns:
            Enhanced image optimized for VLM processing
        """
        # 1. Sharpen the image to make strokes clearer
        kernel_sharpen = np.array([[-1, -1, -1],
                                   [-1,  9, -1],
                                   [-1, -1, -1]])
        sharpened = cv2.filter2D(image, -1, kernel_sharpen)

        # 2. Blend sharpened with original (avoid over-sharpening)
        enhanced = cv2.addWeighted(image, 0.5, sharpened, 0.5, 0)

        # 3. Increase contrast adaptively
        lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l = clahe.apply(l)

        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

        # 4. Slight denoising to clean up without losing detail
        enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 3, 3, 7, 21)

        return enhanced

    @classmethod
    def preprocess_handwritten(cls, image: Union[Image.Image, np.ndarray]) -> Tuple[Image.Image, dict]:
        """
        Full preprocessing pipeline for handwritten documents.

        Args:
            image: PIL Image or OpenCV image

        Returns:
            Tuple of (preprocessed PIL Image, processing report)
        """
        # Convert to OpenCV format if needed
        if isinstance(image, Image.Image):
            cv2_image = cls.pil_to_cv2(image)
        else:
            cv2_image = image.copy()

        report = {
            'operations_applied': [],
            'rotation_angle': 0.0,
            'blue_ink_detected': False
        }

        # 1. Fix rotation first
        cv2_image, angle = cls.fix_rotation(cv2_image)
        if abs(angle) > 0.3:
            report['operations_applied'].append('rotation_fix')
            report['rotation_angle'] = angle

        # 2. Check and enhance blue ink
        hsv = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv, (90, 30, 30), (130, 255, 255))
        blue_ratio = np.sum(blue_mask > 0) / blue_mask.size

        if blue_ratio > 0.0005:
            cv2_image = cls.enhance_blue_ink(cv2_image)
            report['operations_applied'].append('blue_ink_enhancement')
            report['blue_ink_detected'] = True

        # 3. Apply handwritten-specific enhancement
        cv2_image = cls.enhance_handwritten(cv2_image)
        report['operations_applied'].append('handwritten_enhancement')

        # Convert back to PIL
        return cls.cv2_to_pil(cv2_image), report

    @classmethod
    def preprocess(cls, image: Union[Image.Image, np.ndarray],
                   apply_deskew: bool = True,
                   apply_clahe_filter: bool = True,
                   apply_denoise_filter: bool = True,
                   apply_binarize: bool = False) -> Image.Image:
        """
        Apply full preprocessing pipeline

        Args:
            image: PIL Image or OpenCV image
            apply_deskew: Apply deskewing
            apply_clahe_filter: Apply CLAHE contrast enhancement
            apply_denoise_filter: Apply denoising
            apply_binarize: Apply binarization

        Returns:
            Preprocessed PIL Image
        """
        # Convert to OpenCV format if needed
        if isinstance(image, Image.Image):
            cv2_image = cls.pil_to_cv2(image)
        else:
            cv2_image = image

        # Apply preprocessing steps
        if apply_deskew:
            cv2_image = cls.deskew(cv2_image)

        if apply_clahe_filter:
            cv2_image = cls.apply_clahe(cv2_image)

        if apply_denoise_filter:
            cv2_image = cls.denoise(cv2_image)

        if apply_binarize:
            cv2_image = cls.binarize(cv2_image)

        # Convert back to PIL
        return cls.cv2_to_pil(cv2_image)
