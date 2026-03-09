"""
DropMe Server - API Communication and ML Model Interface

Handles:
- QR code generation and scanning
- Phone number recycling
- ML model predictions (lazy-loaded, skipped in dev mode)
- AWS uploads

DEV MODE:
- When SystemInfo.dev is True, ML model is NOT loaded
- Predictions return dummy data for testing
- API calls still work normally
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Self
from gui.aws_uploader import AWSUploader
import time
from datetime import datetime

from PySide6.QtCore import QObject, QUrl, Signal, Slot, QStandardPaths, QDir, QTimer
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QLocalSocket,
    QLocalServer,
)
from PySide6.QtQml import QmlElement, qmlEngine

from gui import PENDING_RECYCLES_FILENAME
from gui import logging
from gui.filequeue import FileQueue

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0

# ==================== API CONSTANTS (UNCHANGED) ====================

SERVER_BASE_URL = "https://dropme.up.railway.app"
MACHINE_NAME = "maadi_club"
MACHINE_API_KEY = b"ojs7JhND.0UEhbrBfyMFstQBjjCG8I3o2fCPTUxb7"
AUTHORIZATION_HEADER = b"Authorization"
AUTHORIZATION_HEADER_VALUE = b"Api-Key " + MACHINE_API_KEY

SEND_ITEM_REQUEST = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/recycle/update/V2/{MACHINE_NAME}/"))
SEND_ITEM_REQUEST.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)
SEND_ITEM_REQUEST.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
SEND_ITEM_PLASTIC_BOTTLE = b'{"bottles": 1, "cans": 0}'
SEND_ITEM_ALUMINUM_CAN = b'{"bottles": 0, "cans": 1}'

GET_QRCODE_REQUEST = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/qrcode/{MACHINE_NAME}/"))
GET_QRCODE_REQUEST.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)

CHECK_QRCODE_SCANNED_REQUEST = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/recycle/check/{MACHINE_NAME}/"))
CHECK_QRCODE_SCANNED_REQUEST.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)

FINISH_RECYCLE_QRCODE_REQUEST = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/recycle/finish/{MACHINE_NAME}/"))
FINISH_RECYCLE_QRCODE_REQUEST.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)
FINISH_RECYCLE_QRCODE_REQUEST.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
FINISH_RECYCLE_QRCODE_DATA = b'""'

# Keep end-of-session UX responsive when network is slow/unreachable.
PHONE_FINISH_REQUEST_TIMEOUT_MS = 2500


# ==================== DATA MODELS ====================

@dataclass(slots=True)
class RecycleData:
    bottles: int = 0
    cans: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, buffer: str | bytes) -> Self:
        return cls(**json.loads(buffer))


@dataclass(slots=True)
class Recycle(RecycleData):
    phoneNumber: str = ""

    def data(self) -> RecycleData:
        # Keep exact payload shape used in your API call (bottles/cans only)
        return RecycleData(self.bottles, self.cans)


# ==================== SERVER (QML ELEMENT) ====================

@QmlElement
class Server(QObject):
    # QML Signals (UNCHANGED)
    qrCodeChanged = Signal(str)
    qrCodeScanned = Signal()
    canInserted = Signal()
    plasticInserted = Signal()
    otherInserted = Signal()
    finishedPhoneNumberRecycle = Signal(bool)  # isPending
    suspendVideos = Signal()
    continueVideos = Signal()

    # Prediction result: [item, qml_uri], capturePath, system_path_to_delete
    predictionReady = Signal(list, str, str)

    def __init__(self) -> None:
        super().__init__()

        self.logger = logging.getLogger("dropme.server")

        # Runtime data directory (Qt-managed, cross-platform)
        self.data_dir = QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        if not self.data_dir.exists():
            self.data_dir.mkpath(".")

        self.uploader = AWSUploader()

        # ==================== DEV MODE + ML (lazy loaded) ====================
        self._mlmodel = None
        self._mlmodel_loaded = False
        self._mlmodel_loading = False
        self._ml_lock = threading.Lock()

        # SystemInfo singleton cache (for dev flag)
        self._system_info = None

        # Session state (kept)
        self.current_phone_number: Optional[str] = None
        self.current_user_id = None
        self.pending_capture_path: Optional[str] = None

        # ==================== NETWORK MANAGERS ====================
        self.qrcode_manager = QNetworkAccessManager(self)
        self.qrcode_manager.finished.connect(self.handleQrCodeResponse)

        self.qrcode_manager_scanned = QNetworkAccessManager(self)
        self.qrcode_manager_scanned.finished.connect(self.handleQrCodeScannedResponse)

        self.finish_recycle_phone_number_manager = QNetworkAccessManager(self)
        self.finish_recycle_phone_number_manager.finished.connect(self.handleFinishRecyclePhoneNumber)

        self.recycle = QNetworkAccessManager(self)
        self.recycle.finished.connect(self.handleRecycleResponse)
        self.recycle.setAutoDeleteReplies(True)

        self.pending_recycles_queue = FileQueue(self.data_dir.filePath(PENDING_RECYCLES_FILENAME))

        # ==================== LOCAL IPC (QLocalServer) ====================
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.handle_new_connection)

        socket_path = self.data_dir.filePath("socket.pipe")

        # Robustness: remove stale server name (common after unclean shutdown)
        try:
            QLocalServer.removeServer(socket_path)
        except Exception:
            pass

        if not self.server.listen(socket_path):
            self.logger.warning(f"IPC server failed to listen on {socket_path}: {self.server.errorString()}")

        self.logger.info("Server initialized (ML model will be lazy-loaded)")

    # ==================== DEV MODE HELPERS ====================

    def _get_system_info(self):
        """
        Best-effort access to the DropMe.SystemInfo QML singleton.
        Safe even if engine not ready.
        """
        if self._system_info is not None:
            return self._system_info

        try:
            eng = qmlEngine(self)
            if eng is None:
                return None

            # PySide6: singletonInstance(moduleName, typeName)
            self._system_info = eng.singletonInstance("DropMe", "SystemInfo")
        except Exception:
            self._system_info = None

        return self._system_info

    def _is_dev_mode(self) -> bool:
        """True when the app runs in UI dev mode (windowed tools, test controls)."""
        si = self._get_system_info()
        if si is not None:
            return bool(getattr(si, "dev_mode", False))
        return os.environ.get("DROPME_DEV", "0") == "1"

    def _should_skip_ml_in_dev(self) -> bool:
        """In --dev mode, skip ML inference and model loading unconditionally."""
        return self._is_dev_mode()

    def _ensure_mlmodel(self) -> bool:
        """
        Ensure ML model is loaded.
        Returns True if model is available, False otherwise.
        In dev mode: always returns False (model not needed).
        """
        if self._should_skip_ml_in_dev():
            self.logger.info("Dev mode enabled - ML model not loaded")
            return False

        if self._mlmodel_loaded:
            return True

        # Make loading thread-safe and prevent double-load
        with self._ml_lock:
            if self._mlmodel_loaded:
                return True
            if self._mlmodel_loading:
                return False

            self._mlmodel_loading = True

        try:
            self.logger.info("Loading ML model...")
            from gui.mlmodel import MLModel  # local import (keeps startup fast)

            model = MLModel(logger=self.logger)
            self._mlmodel = model
            self._mlmodel_loaded = True

            # Warmup in background (unchanged behavior)
            threading.Thread(target=model.warmup, daemon=True).start()

            self.logger.info("ML model loaded successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load ML model: {e}")
            with self._ml_lock:
                self._mlmodel_loading = False
            return False

    @property
    def mlmodel(self):
        """Access ML model (lazy-loaded)."""
        self._ensure_mlmodel()
        return self._mlmodel

    # ==================== IPC HANDLERS ====================

    def handle_new_connection(self) -> None:
        client = self.server.nextPendingConnection()
        if client is None:
            return
        client.setReadBufferSize(3)
        client.readyRead.connect(self.handle_client_ready_read)

    def handle_client_ready_read(self) -> None:
        client = self.sender()
        if not isinstance(client, QLocalSocket):
            return

        buffer = bytearray(3)
        client.read(buffer, 3)

        if buffer == b"\x0F\x00\x00":
            self.suspendVideos.emit()
            client.write(b"\x0F\xCC\x00")
        elif buffer == b"\x0F\x00\x01":
            self.continueVideos.emit()
            client.write(b"\x0F\xCC\x01")

    # ==================== GUI UPDATE ====================

    @Slot()
    def updateGUI(self) -> None:
        """
        Keeps the original behavior:
        - Uses XDG_STATE_HOME (Linux style) fallback to ~/.local/state
        - Runs uv to update GUI in that folder

        Adds safety: handles Windows environments gracefully (still attempts, but logs if missing).
        """
        base = os.getenv("XDG_STATE_HOME", "~/.local/state")
        current_gui_dir = Path(base).expanduser().joinpath("dropme/gui")

        if not current_gui_dir.exists():
            self.logger.warning(f"updateGUI: directory not found: {current_gui_dir}")
            # Keep behavior: still attempt to run (if your deployment creates it later)
        try:
            subprocess.Popen(
                ["uv", "run", "python", "sv.py", "update-gui"],
                cwd=str(current_gui_dir),
                start_new_session=True,
            )
        except Exception as e:
            self.logger.error(f"updateGUI failed: {e}")

    # ==================== RECYCLING API ====================

    @Slot()
    def sendAluminumCan(self) -> None:
        self.recycle.post(SEND_ITEM_REQUEST, SEND_ITEM_ALUMINUM_CAN)

    @Slot()
    def sendPlasticBottle(self) -> None:
        self.recycle.post(SEND_ITEM_REQUEST, SEND_ITEM_PLASTIC_BOTTLE)

    @Slot()
    def finishRecycleQrCode(self) -> None:
        self.recycle.post(FINISH_RECYCLE_QRCODE_REQUEST, FINISH_RECYCLE_QRCODE_DATA)

    @Slot(str, int, int)
    def finishRecyclePhoneNumber(self, phone_number: str, bottles: int, cans: int) -> None:
        req = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/recycle/add/{MACHINE_NAME}/{phone_number}/"))
        req.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        try:
            req.setTransferTimeout(PHONE_FINISH_REQUEST_TIMEOUT_MS)
        except Exception:
            pass

        recycle = Recycle(bottles, cans, phone_number)

        # Keep original behavior: queue locally then attempt send
        self.pending_recycles_queue.queue(recycle.to_json().encode())
        self.finish_recycle_phone_number_manager.post(req, recycle.data().to_json().encode())
        self.logger.info(recycle.to_json())

    # ========== NEW: Dev-mode simulated prediction uploader ==========
    # ========== NEW: Dev-mode simulated prediction uploader ==========
    @Slot(str, str)
    def sendDevPrediction(self, item: str, capturePath: str = "") -> None:
        """
        Dev slot used by QML to simulate a prediction upload.
        ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Reuses a single AWSUploader instance (no repeated threads / boto init)
        ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Never blocks UI thread with direct S3 put_object
        ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ If offline, it will queue locally and background sync later
        """
        try:
            uploader = getattr(self, "uploader", None)
            if uploader is None:
                self.uploader = AWSUploader()
                uploader = self.uploader

            capture_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            decision_map = {
                "plastic": ("ACCEPTED", "NONE"),
                "aluminum": ("ACCEPTED", "NONE"),
                "hand": ("REJECTED", "HAND_VISIBLE"),
                "other": ("REJECTED", "NONE"),
            }
            decision, reason = decision_map.get(item.lower(), ("REJECTED", "NONE"))

            metadata = {
                "capture_id": capture_id,
                "machine_name": uploader.machine_name,
                "item_type": item.lower(),
                "confidence": 1.0,
                "decision": decision,
                "rejection_reason": reason,
                "timestamp": str(int(time.time())),
                "operation_mode": "dev_manual",
            }

            if capturePath and os.path.exists(capturePath):
                # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ queue upload (non-blocking)
                uploader.upload_prediction(
                    image_path=capturePath,
                    prediction_image_bytes=b"",
                    metadata=metadata,
                )
                self.logger.info(f"Dev-mode upload queued for {item} (capture={Path(capturePath).name})")
            else:
                res = uploader.upload_prediction_metadata_only(metadata)
                self.logger.info(f"Dev-mode metadata-only upload queued: {res}")

        except Exception as e:
            self.logger.error(f"Dev-mode upload failed: {e}")

    # ==================== PREDICTION ====================

    @Slot(str, str)
    def getCapturePrediction(self, capturePath: str, phoneNumber: str = "") -> None:
        """
        Start prediction in a worker thread (production),
        or emit dummy dev-mode result immediately.
        """
        # Track capture for QR flow (unchanged behavior)
        if not phoneNumber:
            self.pending_capture_path = capturePath
            self.logger.info(f"QR flow: Tracking capture {Path(capturePath).name} for user_id update")

        # Optional fast dev mode: skip ML only when explicitly requested.
        if self._should_skip_ml_in_dev():
            self.logger.info(f"Dev mode skip-ML enabled: skipping prediction for {capturePath}")
            self.predictionReady.emit(["none", ""], capturePath, "")
            return

        threading.Thread(
            target=self._runCapturePredictionInThread,
            args=(capturePath, phoneNumber),
            daemon=True,
        ).start()

    def _emit_prediction_ready_mainthread(self, result: list, capturePath: str, system_path: str) -> None:
        """
        Ensures signal emission happens on the Qt main thread.
        (Qt can queue signals from threads, but this is safer and more predictable.)
        """
        QTimer.singleShot(0, lambda: self.predictionReady.emit(result, capturePath, system_path))

    def _runCapturePredictionInThread(self, capturePath: str, phoneNumber: str = "") -> None:
        system_path: Optional[str] = None
        try:
            if not self._ensure_mlmodel() or self._mlmodel is None:
                self.logger.warning("ML model not available")
                self._emit_prediction_ready_mainthread(["error", ""], capturePath, "")
                return

            # Separate phone_number from user_id (keep original logic)
            phone_num = phoneNumber if phoneNumber and not self.current_user_id else None
            user_id = str(self.current_user_id) if self.current_user_id else None

            predictions, buffer = self._mlmodel.predict(
                capturePath,
                phone_number=phone_num,
                user_id=user_id,
            )

            if self.current_user_id:
                self.current_user_id = None

            item = "none"
            qml_uri = ""

            if predictions:
                from gui.mlmodel import Item, Decision

                has_hand = any(d.item == Item.HAND for d in predictions)
                if has_hand:
                    item = "hand"
                else:
                    accepted = [d for d in predictions if d.decision == Decision.ACCEPTED]
                    if accepted:
                        best = max(accepted, key=lambda d: d.confidence)
                        item = self._mlmodel.item_to_server_format.get(best.item, "other")
                    else:
                        item = "other"

                if buffer is not None:
                    # Keep exact behavior: write annotated image to a temp file and return file:// URI
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                        system_path = tf.name
                    with open(system_path, "wb") as f:
                        f.write(buffer.tobytes())
                    qml_uri = f"file://{os.path.abspath(system_path)}"

            self.logger.info(f"Prediction result: {item}")
            self._emit_prediction_ready_mainthread([item, qml_uri], capturePath, system_path or "")

        except Exception as e:
            self.logger.error(f"Prediction failed: {e}")
            if system_path and os.path.exists(system_path):
                try:
                    os.unlink(system_path)
                except OSError:
                    pass
            self._emit_prediction_ready_mainthread(["error", ""], capturePath, "")

    # ==================== QR CODE ====================

    @Slot()
    def getQrCode(self) -> None:
        self.qrcode_manager.get(GET_QRCODE_REQUEST)

    @Slot()
    def checkQrCodeScanned(self) -> None:
        self.qrcode_manager_scanned.get(CHECK_QRCODE_SCANNED_REQUEST)

    # ==================== FILE CLEANUP ====================

    @Slot(str)
    def cleanupFile(self, path: str) -> None:
        """Remove temporary annotated image file."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
                self.logger.info(f"Cleaned up temp file: {path}")
            except Exception as e:
                self.logger.error(f"Failed to delete {path}: {e}")

    # ==================== RESPONSE HANDLERS ====================

    def handleQrCodeResponse(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.logger.error(f"QR code error: {reply.error()}")
            return

        data = reply.readAll().data()
        if not data:
            return

        base64_qrcode = base64.b64encode(data).decode("utf-8")
        self.qrCodeChanged.emit(f"data:image/png;base64,{base64_qrcode}")

    def handleQrCodeScannedResponse(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return

        data = reply.readAll().data().decode("utf-8")
        try:
            payload = json.loads(data)
        except Exception:
            return

        if payload.get("log"):
            self.qrCodeScanned.emit()

    def handleFinishRecyclePhoneNumber(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            # Network failure ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â keep the queued item for a future retry.
            self.finishedPhoneNumberRecycle.emit(True)
            return

        # Bug fix: emit success signal IMMEDIATELY so the UI can proceed.
        # Old code re-queued from the file queue before emitting, which caused
        # the same item to be sent twice and delayed the signal by an extra round-trip.
        self.finishedPhoneNumberRecycle.emit(False)

        # Drain any OTHER items backed up from previous offline sessions, AFTER emitting.
        next_buffer = self.pending_recycles_queue.dequeue()
        if next_buffer is None:
            return

        next_in_queue = Recycle.from_json(next_buffer)
        self.logger.info(f"Draining pending queue item for {next_in_queue.phoneNumber}")
        req = QNetworkRequest(QUrl(f"{SERVER_BASE_URL}/machines/recycle/add/{MACHINE_NAME}/{next_in_queue.phoneNumber}/"))
        req.setRawHeader(AUTHORIZATION_HEADER, AUTHORIZATION_HEADER_VALUE)
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        try:
            req.setTransferTimeout(PHONE_FINISH_REQUEST_TIMEOUT_MS)
        except Exception:
            pass
        self.finish_recycle_phone_number_manager.post(req, next_in_queue.data().to_json().encode())

    def handleRecycleResponse(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.logger.error(f"Recycle API error: {reply.error()}")
            return

        data = reply.readAll().data().decode("utf-8")
        self.logger.info(f"Recycle response: {data}")

        try:
            response = json.loads(data)
        except Exception as e:
            self.logger.error(f"Failed to parse recycle response JSON: {e}")
            return

        user_id = response.get("user_id")
        if user_id is None:
            return

        self.current_user_id = user_id
        self.logger.info(f"Captured user_id: {user_id}")

        # Update pending capture's metadata with user_id (same behavior)
        if self.pending_capture_path and self._mlmodel is not None:
            capture_id = Path(self.pending_capture_path).stem
            self.logger.info(f"Updating capture {capture_id} with user_id={user_id}")

            threading.Thread(
                target=self._mlmodel.aws_uploader.update_metadata_with_user_id,
                args=(capture_id, user_id),
                daemon=True,
            ).start()

            self._mlmodel.brand_recognizer.update_user_id_for_capture(
                self.pending_capture_path,
                user_id,
            )

            self.pending_capture_path = None