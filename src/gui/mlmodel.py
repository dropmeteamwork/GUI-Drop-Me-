import os
import base64
import json
import time
from pathlib import Path
from io import BytesIO
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple, List
import logging
from logging.handlers import TimedRotatingFileHandler

import cv2
import numpy as np
from PIL import Image
import boto3
from botocore.exceptions import ClientError
from ultralytics import YOLO
import torch
import torch.nn as nn
from torchvision import transforms
from torchvision.models import efficientnet_b3, EfficientNet_B3_Weights

from gui.brand_recognizer import BrandRecognizer
from gui.aws_uploader import AWSUploader
from gui.runtime_paths import captures_dir, metadata_dir, model_logs_dir, models_dir
import threading

# ============================================================================
# CONFIGURATION
# ============================================================================
class Config:
    """
    Production configuration.
    Runtime paths are resolved from a shared cross-platform resolver:
      - DROPME_MODELS_DIR (optional override)
      - DROPME_STATE_DIR/XDG_STATE_HOME/LOCALAPPDATA fallback chain
    """
    BASE_MODEL_PATH = models_dir()
    LOG_PATH = model_logs_dir()

    # Ensure directories exist
    BASE_MODEL_PATH.mkdir(parents=True, exist_ok=True)
    LOG_PATH.mkdir(parents=True, exist_ok=True)

    # Model filenames
    YOLO_MODEL_PATH       = BASE_MODEL_PATH / "v8n_5classes_v2.pt"
    CLASSIFIER_MODEL_PATH = BASE_MODEL_PATH / "multihead_b3.pth"

    # Operation mode: 1 = YOLO only, 2 = Classifier only, 3 = both
#    OPERATION_MODE = int(os.getenv('OPERATION_MODE', '1'))

    # Model format selection
#    YOLO_FORMAT       = os.getenv('YOLO_FORMAT', 'auto').lower()
#    CLASSIFIER_FORMAT = os.getenv('CLASSIFIER_FORMAT', 'auto').lower()

    # Operation mode: 1 = YOLO only, 2 = Classifier only, 3 = YOLO + Classifier
    OPERATION_MODE: int = 1  # default

    # Model format selection: 'auto', 'pytorch', 'onnx', or 'openvino'
    YOLO_FORMAT: str = 'openvino'
    CLASSIFIER_FORMAT: str = 'pytorch'


    # AWS configuration
    AWS_ACCESS_KEY_ID  = os.getenv('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY  = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    AWS_BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', '')
    AWS_REGION      = os.getenv('AWS_REGION', 'eu-central-1')
    MACHINE_NAME    = os.getenv('MACHINE_NAME', 'RVM-001')

    # Detection thresholds
    YOLO_CONF_THRESHOLD     = float(os.getenv('YOLO_CONF_THRESHOLD', '0.1'))

    # Per-class ACCEPTANCE thresholds (applied in decision logic)
    # Class IDs: 0=PLASTIC, 1=HAND, 2=CRUSHED_PLASTIC, 3=ALUMINUM, 4=CRUSHED_ALUMINUM
    CLASS_ACCEPT_THRESHOLDS = {
        0: 0.40,  # PLASTIC - must be 90%+ confident
        1: 0.10,  # HAND - lower threshold to catch hands reliably
        2: 0.50,  # CRUSHED_PLASTIC
        3: 0.40,  # ALUMINUM - must be 80%+ confident
        4: 0.50,  # CRUSHED_ALUMINUM
    }
    DEFAULT_CLASS_THRESHOLD = 0.70
    HAND_OVERRIDE_THRESHOLD = float(os.getenv('HAND_OVERRIDE_THRESHOLD', '0.4'))

    CLASSIFIER_CONF_THRESHOLD = float(os.getenv('CLASSIFIER_CONF_THRESHOLD', '0.6'))
    CLASSIFIER_REJECT_THRESHOLD = float(os.getenv('CLASSIFIER_REJECT_THRESHOLD', '0.6'))
    MIN_BOX_AREA           = int(os.getenv('MIN_BOX_AREA', '1000'))
    MAX_BOX_AREA           = int(os.getenv('MAX_BOX_AREA', '300000'))

    # Performance settings
    DEVICE          = os.getenv('DEVICE', 'cpu')
    YOLO_IMG_SIZE   = int(os.getenv('YOLO_IMG_SIZE', '416'))
    MAX_DETECTIONS  = int(os.getenv('MAX_DETECTIONS', '3'))

    # Logging
    LOG_LEVEL        = logging.INFO
    ENABLE_CONSOLE_LOG = bool(os.getenv('ENABLE_CONSOLE_LOG', '0'))
    LOG_BACKUP_COUNT = int(os.getenv('ML_LOG_BACKUP_COUNT', '14'))


def setup_logging() -> logging.Logger:
    """Prepare a logger that writes to the production log directory."""
    log_file = Config.LOG_PATH / "detection.log"
    logger = logging.getLogger("RVM_AI")
    logger.setLevel(Config.LOG_LEVEL)
    logger.handlers.clear()
    fh = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(Config.LOG_LEVEL)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    if Config.ENABLE_CONSOLE_LOG:
        ch = logging.StreamHandler()
        ch.setLevel(Config.LOG_LEVEL)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger


logger = setup_logging()


# ============================================================================
# ENUMS AND DATA STRUCTURES
# ============================================================================
class Item(Enum):
    PLASTIC = "PET"
    ALUMINUM = "CAN"
    HAND = "HAND"
    CRUSHED_PLASTIC = "PET_FULLY_CRUSHED"
    CRUSHED_ALUMINUM = "CAN_FULLY_CRUSHED"
    OTHER = "OTHER"


class Decision(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSURE = "UNSURE"


class RejectionReason(Enum):
    NONE = "NONE"
    CRUSHED = "CRUSHED"
    HAND_VISIBLE = "HAND_VISIBLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    #FOREIGN_OBJECT = "FOREIGN_OBJECT"
    #DAMAGED = "DAMAGED"
    WRONG_TYPE = "WRONG_TYPE"
    #BACKGROUND = "BACKGROUND"
    UNSURE = "UNSURE"


@dataclass
class Detection:
    item: Item
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]
    decision: Decision
    rejection_reason: RejectionReason
    yolo_class_id: Optional[int] = None
    yolo_predicted_item: Optional[Item] = None
    classifier_confidence: Optional[float] = None
    classifier_accept_prob: Optional[float] = None
    classifier_reject_prob: Optional[float] = None
    mode: str = "unknown"


# ============================================================================
# S3 UPLOADER
# ============================================================================
# class S3Uploader:
#     def __init__(self) -> None:
#         self.enabled = bool(Config.AWS_ACCESS_KEY and Config.AWS_SECRET_KEY and Config.AWS_BUCKET_NAME)
#         if self.enabled:
#             try:
#                 self.s3_client = boto3.client(
#                     's3',
#                     aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
#                     aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
#                     region_name=Config.AWS_REGION
#                 )
#                 logger.info("S3 uploader initialised successfully")
#             except Exception as exc:
#                 logger.error(f"Failed to initialise S3 client: {exc}")
#                 self.enabled = False
#         else:
#             logger.warning("S3 uploader disabled – missing AWS credentials")

#     def upload_detection(self, image: np.ndarray, detection: Detection, capture_id: str) -> bool:
#         if not self.enabled:
#             return False
#         try:
#             ok, buffer = cv2.imencode('.jpg', image)
#             if not ok:
#                 logger.error("Failed to encode image for S3 upload")
#                 return False
#             image_bytes = buffer.tobytes()
#             metadata = {
#                 'capture_id': capture_id,
#                 'machine_name': Config.MACHINE_NAME,
#                 'item_type': detection.item.value,
#                 'confidence': f"{detection.confidence:.3f}",
#                 'decision': detection.decision.value,
#                 'rejection_reason': detection.rejection_reason.value,
#                 'timestamp': f"{time.time():.0f}",
#                 'classifier_confidence': f"{(detection.classifier_confidence or 0):.3f}",
#                 'operation_mode': detection.mode
#             }
#             self.s3_client.put_object(
#                 Bucket=Config.AWS_BUCKET_NAME,
#                 Key=f"detections/{capture_id}.jpg",
#                 Body=image_bytes,
#                 Metadata=metadata,
#                 ContentType='image/jpeg'
#             )
#             self.s3_client.put_object(
#                 Bucket=Config.AWS_BUCKET_NAME,
#                 Key=f"metadata/{capture_id}.json",
#                 Body=json.dumps(metadata, indent=2),
#                 ContentType='application/json'
#             )
#             logger.info(f"Uploaded detection {capture_id} to S3")
#             return True
#         except ClientError as exc:
#             logger.error(f"S3 upload failed: {exc}")
#             return False


# ============================================================================
# CLASSIFIER
# ============================================================================
class HumanVisionClassifier(nn.Module):
    def __init__(self, num_classes: int = 5) -> None:
        super().__init__()
        backbone = efficientnet_b3(weights=EfficientNet_B3_Weights.IMAGENET1K_V1)
        for param in list(backbone.parameters())[:-50]:
            param.requires_grad = False
        self.features = backbone.features
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        def make_head(in_features: int) -> nn.Sequential:
            return nn.Sequential(
                nn.Linear(in_features, 512), nn.ReLU(), nn.BatchNorm1d(512), nn.Dropout(0.4),
                nn.Linear(512, 256), nn.ReLU(), nn.BatchNorm1d(256), nn.Dropout(0.3),
                nn.Linear(256, 128), nn.ReLU()
            )
        self.geometry_head = make_head(1536)
        self.lighting_head = make_head(1536)
        self.texture_head = make_head(1536)
        self.fusion = nn.Sequential(
            nn.Linear(128 * 3, 256), nn.ReLU(), nn.Dropout(0.3), nn.Linear(256, 2)
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.features(x)
        features = self.avgpool(features)
        features = features.view(features.size(0), -1)
        geom = self.geometry_head(features)
        light = self.lighting_head(features)
        tex = self.texture_head(features)
        combined = torch.cat([geom, light, tex], dim=1)
        logits = self.fusion(combined)
        return logits


class ClassifierInference:
    def __init__(self, model_path: Path) -> None:
        self.device = Config.DEVICE
        self.model = None
        self.session = None
        self.format_used = 'none'
        onnx_path = model_path.with_suffix('.onnx')
        available = []
        if onnx_path.exists():
            available.append('onnx')
        if model_path.exists():
            available.append('pytorch')
        desired = Config.CLASSIFIER_FORMAT
        fmt = 'pytorch'
        if desired == 'onnx' and 'onnx' in available:
            fmt = 'onnx'
        elif desired == 'auto':
            fmt = 'onnx' if 'onnx' in available else 'pytorch'
        # Load selected
        if fmt == 'onnx':
            self._load_onnx(onnx_path)
        else:
            self._load_pytorch(model_path)
        self.transform = transforms.Compose([
            transforms.Resize((640, 640)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        logger.info(f"Classifier loaded using {self.format_used} format on device {self.device}")
    def _load_onnx(self, path: Path) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            logger.error(f"onnxruntime is not installed: {exc}")
            raise
        self.session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.model = None
        self.format_used = 'ONNX'
    def _load_pytorch(self, path: Path) -> None:
        self.model = HumanVisionClassifier(num_classes=5)
        self.model = self.model.to(self.device)
        checkpoint = torch.load(path, map_location=self.device)
        state_dict = checkpoint.get('model_state_dict', checkpoint) if isinstance(checkpoint, dict) else checkpoint
        if any(k.startswith('module.') for k in state_dict.keys()):
            state_dict = {k.replace('module.', '', 1): v for k, v in state_dict.items()}
        self.model.load_state_dict(state_dict, strict=True)
        self.model.eval()
        self.session = None
        self.format_used = 'PyTorch'
    @torch.no_grad()
    def _run(self, tensor: torch.Tensor) -> torch.Tensor:
        if self.session is not None:
            out = self.session.run(None, {self.input_name: tensor.numpy()})
            return torch.from_numpy(out[0])
        return self.model(tensor.to(self.device))
    
    # @torch.no_grad()
    # def classify_crop(self, crop: np.ndarray) -> Tuple[Item, str, float, float]:
    #     rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    #     pil = Image.fromarray(rgb)
    #     tensor = self.transform(pil).unsqueeze(0)
    #     logits = self._run(tensor)
    #     probs = torch.softmax(logits, dim=1)
    #     reject_prob = probs[0, 0].item()
    #     accept_prob = probs[0, 1].item()
    #     if accept_prob >= Config.CLASSIFIER_CONF_THRESHOLD:
    #         return Item.PLASTIC, 'ACCEPT', accept_prob, reject_prob
    #     if reject_prob >= Config.CLASSIFIER_REJECT_THRESHOLD:
    #         return Item.OTHER, 'REJECT', accept_prob, reject_prob
    #     return Item.OTHER, 'UNSURE', accept_prob, reject_prob

    @torch.no_grad()
    def classify_full(self, image: np.ndarray) -> Tuple[Item, str, float, float]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        tensor = self.transform(pil).unsqueeze(0)
        logits = self._run(tensor)
        probs = torch.softmax(logits, dim=1)
        reject_prob = probs[0, 0].item()
        accept_prob = probs[0, 1].item()
        if accept_prob >= Config.CLASSIFIER_CONF_THRESHOLD:
            return Item.PLASTIC, 'ACCEPT', accept_prob, reject_prob
        if reject_prob >= Config.CLASSIFIER_REJECT_THRESHOLD:
            return Item.OTHER, 'REJECT', accept_prob, reject_prob
        return Item.OTHER, 'UNSURE', accept_prob, reject_prob

    @torch.no_grad()
    def classify_crop(self, crop: np.ndarray) -> Tuple[Item, str, float, float]:
        return self.classify_full(crop)

# ============================================================================
# YOLO DETECTOR
# ============================================================================
class YOLODetector:
    def __init__(self, path: Path) -> None:
        base = path.parent / path.stem
        ov_dir = Path(str(base) + "_openvino_model")
        onnx_file = base.with_suffix('.onnx')
        avail = {}
        if ov_dir.exists():
            avail['openvino'] = ov_dir
        if onnx_file.exists():
            avail['onnx'] = onnx_file
        if path.exists():
            avail['pytorch'] = path
        desired = Config.YOLO_FORMAT
        fmt = 'pytorch'
        if desired in avail:
            fmt = desired
        elif desired == 'auto':
            if 'openvino' in avail:
                fmt = 'openvino'
            elif 'onnx' in avail:
                fmt = 'onnx'
            elif 'pytorch' in avail:
                fmt = 'pytorch'
        if fmt == 'openvino':
            self.model = YOLO(str(avail['openvino']))
            self.format_used = 'OpenVINO'

        elif fmt == 'onnx':
            self.model = YOLO(str(avail['onnx']))
            self.format_used = 'ONNX'
        else:
            self.model = YOLO(str(avail.get('pytorch', path)))
            self.format_used = 'PyTorch'
        self.yolo_class_to_item = {0: Item.PLASTIC, 1: Item.HAND, 2: Item.CRUSHED_PLASTIC, 3: Item.ALUMINUM, 4: Item.CRUSHED_ALUMINUM}
        logger.info(f"YOLO loaded using {self.format_used} format on device {Config.DEVICE}")
    def detect(self, image: np.ndarray) -> List[Tuple[int, int, int, int, float, int]]:
        try:
            #results = self.model([image], imgsz=Config.YOLO_IMG_SIZE, conf=Config.YOLO_CONF_THRESHOLD)
            out: List[Tuple[int, int, int, int, float, int]] = []

            results = self.model.predict(
            image,
            imgsz=Config.YOLO_IMG_SIZE,
            conf=Config.YOLO_CONF_THRESHOLD,
            max_det=Config.MAX_DETECTIONS
            )
            for res in results:
                boxes = getattr(res, 'boxes', [])
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    out.append((x1, y1, x2, y2, conf, cls_id))
                    #area = (x2 - x1) * (y2 - y1)
                    #if Config.MIN_BOX_AREA <= area <= Config.MAX_BOX_AREA:
                     #   out.append((x1, y1, x2, y2, conf, cls_id))
            return out
        except Exception as exc:
            logger.error(f"YOLO detection error: {exc}")
            return []


# ============================================================================
# MAIN ML MODEL
# ============================================================================
class MLModel:
    def __init__(self, logger,model_path=None):
        """
        Initialise the ML pipeline.  An optional ``model_path`` argument is
        accepted for compatibility but ignored; the configuration values
        determine which models to load.
        """
        self.logger = logger
        logger.info(f"Initialising MLModel in mode {Config.OPERATION_MODE}")
        self.mode = Config.OPERATION_MODE
        self.model = None

        # <<< INSERT PYTORCH OPTIMIZATION HERE >>>
        # Assuming you have 4 logical cores available for PyTorch:
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        # <<< END PYTORCH OPTIMIZATION >>>


        self.yolo: Optional[YOLODetector] = None
        self.classifier: Optional[ClassifierInference] = None
        # NEW: warmup state flag
        self._warmed_up = False

        if self.mode in (1, 3):
            self.yolo = YOLODetector(Config.YOLO_MODEL_PATH)
        if self.mode in (2, 3):
            self.classifier = ClassifierInference(Config.CLASSIFIER_MODEL_PATH)
        #self.s3_uploader = S3Uploader()
        self.item_to_server_format = {
            Item.PLASTIC: "plastic",
            Item.ALUMINUM: "aluminum",
            Item.HAND: "hand",
            Item.CRUSHED_PLASTIC: "other",
            Item.CRUSHED_ALUMINUM: "other",
            Item.OTHER: "other"
        }
        self.aws_uploader = AWSUploader()  # new uploader
        # NEW: start backfill worker in background
#        threading.Thread(
#            target=self._backfill_unprocessed_captures_bg,
#            daemon=True,
#        ).start()

        self.brand_recognizer = BrandRecognizer(logger, Config)

    # ====================================================================================
    # BACKFILL FUNCTIONS (RUN ANY CAPTURES WITHOUT METADATA THROUGH ML PIPELINE)
    # ====================================================================================
    def _backfill_unprocessed_captures_bg(self):
        """
        Background worker to backfill captures that have no metadata yet.
        Runs once at startup in a separate thread.
        """
        try:
            time.sleep(5)  # optional: let system start first
            self.logger.info("Starting background backfill of unprocessed captures...")
            count = self._backfill_unprocessed_captures_once()
            self.logger.info(f"Background backfill finished. Processed {count} captures.")
        except Exception as e:
            self.logger.error(f"Backfill worker failed: {e}", exc_info=True)

    def _backfill_unprocessed_captures_once(self) -> int:
        """
        Run ML on any capture images that do NOT yet have metadata.
        Uses the normal predict() pipeline (YOLO + classifier + AWS queue).
        Returns how many images were processed.
        """
        captures_dir_path = captures_dir()
        metadata_dir_path = metadata_dir()

        if not captures_dir_path.exists():
            self.logger.info("No captures_dir found for backfill.")
            return 0

        processed = 0
        for img_path in captures_dir_path.glob("*.jpg"):
            capture_id = img_path.stem
            meta_path = metadata_dir_path / f"{capture_id}.json"

            # Only process captures that have NO metadata yet
            if not meta_path.exists():
                self.logger.info(f"[Backfill] Running ML on {img_path}")

                # THIS is the magic — this uses the FULL ML pipeline:
                #  - runs YOLO / classifier
                #  - produces real detections
                #  - annotates
                #  - creates correct metadata (operation_mode, model versions, timings)
                #  - queues upload via aws_uploader
                self.predict(str(img_path))

                processed += 1
                time.sleep(0.1)  # throttle to avoid CPU spike

        return processed

    # Helper methods
    def select_final_detection(self, dets: List[Detection]) -> Optional[Detection]:
        if not dets:
            return None

        hand_candidates = [
            d for d in dets
            if d.item == Item.HAND and d.confidence >= Config.HAND_OVERRIDE_THRESHOLD
        ]
        if hand_candidates:
            return max(hand_candidates, key=lambda d: d.confidence)

        non_hand = [d for d in dets if d.item != Item.HAND]
        if non_hand:
            return max(non_hand, key=lambda d: d.confidence)

        return max(dets, key=lambda d: d.confidence)

    def _crop(self, image: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = bbox
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        return image[y1:y2, x1:x2]

    def _decision_mode1(self, cls_id: int, confidence: float) -> Tuple[Item, Decision, RejectionReason]:
        """
        Make accept/reject decision based on YOLO detection.
        Uses per-class confidence thresholds.
        """
        item = self.yolo.yolo_class_to_item.get(cls_id, Item.OTHER) if self.yolo else Item.OTHER

        # Get the threshold for this specific class ID
        threshold = Config.CLASS_ACCEPT_THRESHOLDS.get(cls_id, Config.DEFAULT_CLASS_THRESHOLD)

        # Check if confidence meets the class-specific threshold
        if confidence < threshold:
            logger.info(f"[Mode1] {item.value} conf={confidence:.2f} below threshold {threshold:.2f} -> LOW_CONFIDENCE")
            return item, Decision.REJECTED, RejectionReason.LOW_CONFIDENCE

        # Original logic for items that pass threshold
        if item == Item.HAND:
            return item, Decision.REJECTED, RejectionReason.HAND_VISIBLE
        if item in (Item.CRUSHED_PLASTIC, Item.CRUSHED_ALUMINUM):
            return item, Decision.REJECTED, RejectionReason.CRUSHED
        if item in (Item.PLASTIC, Item.ALUMINUM):
            return item, Decision.ACCEPTED, RejectionReason.NONE

        return item, Decision.REJECTED, RejectionReason.WRONG_TYPE

    def _decision_mode2(self, item: Item, dec: str) -> Tuple[Decision, RejectionReason]:
        if dec == 'ACCEPT':
            return Decision.ACCEPTED, RejectionReason.NONE
        if dec == 'REJECT':
            return Decision.REJECTED, RejectionReason.LOW_CONFIDENCE
        return Decision.UNSURE, RejectionReason.UNSURE

    def _decision_mode3(self, y_item: Item, y_conf: float, y_cls_id: int,
                        c_item: Item, c_dec: str) -> Tuple[Decision, RejectionReason]:
        """Combined YOLO + Classifier decision with per-class thresholds."""

        # Get YOLO threshold for the detected class
        yolo_threshold = Config.CLASS_ACCEPT_THRESHOLDS.get(y_cls_id, Config.DEFAULT_CLASS_THRESHOLD)

        # YOLO confidence too low for this class
        if y_conf < yolo_threshold:
            return Decision.REJECTED, RejectionReason.LOW_CONFIDENCE

        # Hand always rejected
        if y_item == Item.HAND:
            return Decision.REJECTED, RejectionReason.HAND_VISIBLE

        # Crushed items always rejected
        if y_item in (Item.CRUSHED_PLASTIC, Item.CRUSHED_ALUMINUM):
            return Decision.REJECTED, RejectionReason.CRUSHED

        # Use classifier decision for final accept/reject
        if c_dec == 'ACCEPT':
            return Decision.ACCEPTED, RejectionReason.NONE
        if c_dec == 'REJECT':
            return Decision.REJECTED, RejectionReason.LOW_CONFIDENCE

        return Decision.UNSURE, RejectionReason.UNSURE


    def _annotate(self, img: np.ndarray, det: Detection) -> np.ndarray:
        out = img.copy()
        if det.bbox:
            x1, y1, x2, y2 = det.bbox
            if det.decision == Decision.ACCEPTED:
                colour = (255, 0, 0)  # NEW: Blue (BGR format)
            elif det.decision == Decision.REJECTED:
                colour = (0, 0, 255)  # red
            else:
                colour = (255, 165, 0) # orange if unsure
            cv2.rectangle(out, (x1, y1), (x2, y2), colour, 3)
            #label = det.item.value
            label = f"{det.item.value} ({det.confidence:.2f})"
            if det.mode == 'yolo_classifier' and det.yolo_predicted_item:
                label = f"YOLO: {det.yolo_predicted_item.value} | Cls: {det.item.value}"
            label += f" | {det.decision.value}"
            if det.classifier_accept_prob is not None:
                label += f" | A:{det.classifier_accept_prob:.2f} R:{det.classifier_reject_prob:.2f}"

            font_scale = 0.6
            font_thickness = 2

            #(tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)

            cv2.rectangle(out, (x1, y1 - th - 10), (x1 + tw, y1), colour, -1)
            #cv2.putText(out, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(out, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        else:
            label = f"Full Image: {det.decision.value} (acc={det.classifier_confidence:.2f})"
            col = (0, 255, 0) if det.decision == Decision.ACCEPTED else (0, 0, 255)
            cv2.putText(out, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2)
        return out
    # Mode predictions



################ with time tracking
    def predict_mode1(self, img: np.ndarray) -> Tuple[List[Detection], float]:
        """Returns (detections, yolo_time_ms)"""
        dets: List[Detection] = []

        t0 = time.perf_counter()
        yolo_results = self.yolo.detect(img) if self.yolo else []
        t1 = time.perf_counter()
        yolo_ms = (t1 - t0) * 1000.0

        for x1, y1, x2, y2, conf, cls_id in yolo_results:
            # Pass confidence to decision function for per-class thresholding
            item, dec, reason = self._decision_mode1(cls_id, conf)
            dets.append(Detection(
                item=item,
                confidence=conf,
                bbox=(x1, y1, x2, y2),
                decision=dec,
                rejection_reason=reason,
                yolo_class_id=cls_id,
                mode='yolo_only'
            ))
            logger.info(
                f"[Mode1] {item.value} conf={conf:.2f} decision={dec.value} "
                f"reason={reason.value}"
            )

        return dets, yolo_ms

    def predict_mode2(self, img: np.ndarray) -> List[Detection]:
        item, dec_str, accept_prob, reject_prob = self.classifier.classify_full(img) if self.classifier else (Item.OTHER, 'REJECT', 0.0, 1.0)
        dec, reason = self._decision_mode2(item, dec_str)
        conf_val = accept_prob if dec == Decision.ACCEPTED else reject_prob
        d = Detection(item=item, confidence=conf_val, bbox=None, decision=dec, rejection_reason=reason, classifier_confidence=conf_val, classifier_accept_prob=accept_prob, classifier_reject_prob=reject_prob, mode='classifier_only')
        logger.info(f"[Mode2] Full image accept={accept_prob:.2f} reject={reject_prob:.2f} decision={dec.value}")
        return [d]
    def predict_mode3(self, img: np.ndarray) -> List[Detection]:
        yolo_out = self.yolo.detect(img) if self.yolo else []
        if not yolo_out:
            logger.info("No YOLO detections; falling back to classifier")
            return self.predict_mode2(img)
        dets: List[Detection] = []
        for x1, y1, x2, y2, conf, cls_id in yolo_out:
            bbox = (x1, y1, x2, y2)
            y_item = self.yolo.yolo_class_to_item.get(cls_id, Item.OTHER)
            crop = self._crop(img, bbox)
            c_item, c_dec, a_prob, r_prob = self.classifier.classify_crop(crop) if self.classifier else (Item.OTHER, 'REJECT', 0.0, 1.0)
            #dec, reason = self._decision_mode3(y_item, c_item, c_dec)
            dec, reason = self._decision_mode3(y_item, conf, cls_id, c_item, c_dec)
            c_conf = a_prob if dec == Decision.ACCEPTED else r_prob
            final_item = y_item if y_item in (Item.HAND, Item.CRUSHED_PLASTIC, Item.CRUSHED_ALUMINUM) else c_item
            dets.append(Detection(item=final_item, confidence=conf, bbox=bbox, decision=dec, rejection_reason=reason, yolo_class_id=cls_id, yolo_predicted_item=y_item, classifier_confidence=c_conf, classifier_accept_prob=a_prob, classifier_reject_prob=r_prob, mode='yolo_classifier'))
            logger.info(f"[Mode3] YOLO: {y_item.value} ({conf:.2f}) | Cls: {c_item.value} (A={a_prob:.2f}, R={r_prob:.2f}) | Final: {final_item.value} -> {dec.value}")
        return dets

    ######################################## predict with time tracking
    def predict(self, image_path: str, phone_number: Optional[str] = None, user_id: Optional[str] = None) -> Tuple[List[Detection], Optional[np.ndarray]]:
        """
        Run the full pipeline on a single image and collect timing info.

        Returns:
            dets:   list of Detection
            buffer: PNG-encoded annotated image as np.ndarray (or None on error)
        """
        t_total_start = time.perf_counter()
        timings: dict = {}

        logger.info(f"Processing {image_path} (mode {self.mode})")
        buffer: Optional[np.ndarray] = None

        try:
            # 1) Load image from disk
            t0 = time.perf_counter()
            img = cv2.imread(image_path)
            t1 = time.perf_counter()
            timings["load_image_ms"] = int((t1 - t0) * 1000.0)

            if img is None:
                logger.error(f"Unable to read image: {image_path}")
                return [], None

            # 2) Core inference (depends on mode)
            if self.mode == 1:
                dets, yolo_ms = self.predict_mode1(img)
                timings["yolo_ms"] = int(yolo_ms)

            elif self.mode == 2:
                t0 = time.perf_counter()
                dets = self.predict_mode2(img)
                t1 = time.perf_counter()
                timings["classifier_full_ms"] = int((t1 - t0) * 1000.0)

            elif self.mode == 3:
                t0 = time.perf_counter()
                dets = self.predict_mode3(img)
                t1 = time.perf_counter()
                # This is combined YOLO + classifier per-crop; if you want more
                # detail, you can instrument predict_mode3 similarly.
                timings["yolo_plus_classifier_ms"] = int((t1 - t0) * 1000.0)

            else:
                logger.error(f"Invalid operation mode: {self.mode}")
                return [], None

            # 3) Annotation (drawing boxes / labels)
            t0 = time.perf_counter()
            annotated = img.copy()
            if dets:
                final_det = self.select_final_detection(dets)
                if final_det is not None:
                    annotated = self._annotate(annotated, final_det)
            else:
                cv2.putText(
                    annotated,
                    "No detections",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 0, 255),
                    2
                )
            t1 = time.perf_counter()
            timings["annotate_ms"] = int((t1 - t0) * 1000.0)

            # 4) Encode annotated image as PNG
            t0 = time.perf_counter()
            ok, buffer = cv2.imencode('.png', annotated)
            t1 = time.perf_counter()
            timings["encode_png_ms"] = int((t1 - t0) * 1000.0)

            if not ok:
                logger.error("Failed to encode image to PNG buffer.")
                buffer = None

            # 5) Queue AWS upload (non-blocking) with timings included
            #if dets and self.aws_uploader.s3_client is not None and buffer is not None:
            if dets and buffer is not None:
                best = self.select_final_detection(dets)
                if best is None:
                    return dets, buffer
                item_str = self.item_to_server_format[best.item]
                decision_str = best.decision.value

                # NOTE: prediction_image_bytes is not used by the uploader
                # right now, but we pass it to match the signature.
                prediction_image_bytes = buffer.tobytes()

                # Model names (None if that model isn't in use)
                yolo_model_name = Config.YOLO_MODEL_PATH.stem if self.yolo is not None else None
                classifier_model_name = (
                    Config.CLASSIFIER_MODEL_PATH.stem if self.classifier is not None else None
                )

                # Map numeric mode -> string for metadata
                if self.mode == 1:
                    op_mode_str = "yolo_only"
                elif self.mode == 2:
                    op_mode_str = "classifier_only"
                elif self.mode == 3:
                    op_mode_str = "yolo_plus_classifier"
                else:
                    op_mode_str = "unknown"

#                complete_metadata = {
#                    'image_path': image_path,
#                    'item': item_str,
#                    'confidence': float(best.confidence),
#                    'prediction_image_bytes': prediction_image_bytes,
#                    'machine_name': Config.MACHINE_NAME,
#                    'status': decision_str,
#                    'bbox': best.bbox,
#                    'timings': timings,
#                    'yolo_model': yolo_model_name,
#                    'classifier_model': classifier_model_name,
#                    'operation_mode': op_mode_str,
#                    'phone_number': phone_number,
#                    'user_id': user_id,  # ADD THIS - pass user_id
#
                complete_metadata = {
                    'capture_id': Path(image_path).stem,
                    'machine_name': Config.MACHINE_NAME,
                    'item_type': item_str,
                    'confidence': round(float(best.confidence), 3),
                    'decision': decision_str,
                    'rejection_reason': best.rejection_reason.value,
                    'timestamp': str(int(time.time())),
                    'operation_mode': op_mode_str,
                    'yolo_model': yolo_model_name,
                    'classifier_model': classifier_model_name,
                    'bbox': {'x1': best.bbox[0], 'y1': best.bbox[1],
                             'x2': best.bbox[2], 'y2': best.bbox[3]} if best.bbox else None,
                    'phone_number': phone_number,
                    'user_id': user_id,
                    'yolo_class_id': best.yolo_class_id,
                    'yolo_predicted_item': best.yolo_predicted_item.value if best.yolo_predicted_item else None,
                    'classifier_confidence': best.classifier_confidence,
                    'classifier_accept_prob': best.classifier_accept_prob,
                    'classifier_reject_prob': best.classifier_reject_prob,
                    'timings': timings.copy() if timings else {}
                }

                # ✅ Pass complete metadata to AWS uploader
                threading.Thread(
                    target=self.aws_uploader.upload_prediction,
                    kwargs={
                        'image_path': image_path,
                        'prediction_image_bytes': prediction_image_bytes,
                        'metadata': complete_metadata  # ✅ Pass entire metadata dict
                    },
                    daemon=True,
                ).start()

                # Use kwargs so we don't mess up argument order
#                threading.Thread(
#                    target=self.aws_uploader.upload_prediction,
#                    kwargs={
#                        'image_path': image_path,
#                        'item': item_str,
#                        'confidence': float(best.confidence),
#                        'prediction_image_bytes': prediction_image_bytes,
#                        'machine_name': Config.MACHINE_NAME,
#                        'status': decision_str,
#                        'bbox': best.bbox,
#                        'timings': timings,
#                        'yolo_model': yolo_model_name,
#                        'classifier_model': classifier_model_name,
#                        'operation_mode': op_mode_str,
#                        'phone_number': phone_number,
#                        'user_id': user_id,  # ADD THIS - pass user_id
#                    },
#                    daemon=True,
#                ).start()

            # 6) Total time
            t_total_end = time.perf_counter()
            timings["total_ms"] = int((t_total_end - t_total_start) * 1000.0)

            logger.info(
                f"Finished processing in {timings['total_ms']/1000.0:.3f}s; "
                f"detections={len(dets)}; timings={timings}"
            )

            # Queue accepted items for brand recognition
            if dets and self.brand_recognizer:
                for d in dets:
                    # Only process ACCEPTED plastic or aluminum items
                    if d.decision == Decision.ACCEPTED and d.bbox:
                        if d.item in (Item.PLASTIC, Item.ALUMINUM):
                            # Crop the detection
                            x1, y1, x2, y2 = d.bbox
                            cropped = img[y1:y2, x1:x2]

                            # Map item type for brand recognizer
                            item_type = "plastic" if d.item == Item.PLASTIC else "aluminum"

                            # Queue for background processing
                            self.brand_recognizer.queue_item(
                                image_path=image_path,
                                cropped_image=cropped,
                                metadata=complete_metadata  # ✅ Same metadata object

#                                item_type=item_type,
#                                phone_number=phone_number,
#                                user_id=user_id  # ADD THIS
                            )

            return dets, buffer

        except Exception as exc:
            logger.error(f"Prediction error: {exc}", exc_info=True)
            return [], None




    def warmup(self):
        """
        Warm up the *full* detection pipeline once:

        - Create a dummy image on disk
        - Run self.predict(...) on it (YOLO + classifier + cv2 + encode)
        - Do NOT upload anything to AWS
        """

        # Run only once
        if self._warmed_up:
            self.logger.info("Warmup already done, skipping.")
            return

        self._warmed_up = True
        self.logger.info("Starting FULL ML pipeline warm-up...")
        start = time.time()

        # Create a dummy image with the same size YOLO expects
        dummy_img = np.random.randint(
            0, 255,
            (Config.YOLO_IMG_SIZE, Config.YOLO_IMG_SIZE, 3),
            dtype=np.uint8
        )

        temp_file = None
        dummy_path = ""
        try:
            import tempfile

            temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            dummy_path = temp_file.name
            temp_file.close()

            # Write dummy image to disk so predict() follows the real path
            if not cv2.imwrite(dummy_path, dummy_img):
                raise RuntimeError(f"Failed to write warmup image to {dummy_path}")

            # Temporarily disable AWS uploads during warmup
            aws_client_backup = getattr(self.aws_uploader, "s3_client", None)
            self.aws_uploader.s3_client = None

            try:
                dets, _ = self.predict(dummy_path)
                self.logger.info(
                    f"Warmup prediction finished, detections={len(dets)}"
                )
            finally:
                # Restore AWS uploader state
                self.aws_uploader.s3_client = aws_client_backup

        except Exception as e:
            self.logger.error(f"Warmup failed: {e}", exc_info=True)
        finally:
            try:
                if dummy_path and os.path.exists(dummy_path):
                    os.remove(dummy_path)
            except OSError:
                pass

        elapsed = time.time() - start
        self.logger.info(f"FULL ML warm-up completed in {elapsed:.2f}s")


    def load_model_async(self):
            """Forces the OpenVINO model to load/compile on startup."""
            try:
                # Accessing the model property or calling a non-destructive method
                # forces the OpenVINO initialization/compilation to happen here.
                # Replace 'self.model' with whatever triggers the actual OpenVINO model load.
                _ = self.model
                self.logger.info("OpenVINO model loaded/compiled successfully in background.")
            except Exception as e:
                self.logger.error(f"Failed to load OpenVINO model asynchronously: {e}")
