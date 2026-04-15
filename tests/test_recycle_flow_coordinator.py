from tests.qt_test_stubs import import_with_fake_pyside

recycle_flow_module = import_with_fake_pyside("gui.recycle_flow_coordinator")


class FakeSerial:
    def __init__(self):
        self.calls = []

    def sendSignOut(self):
        self.calls.append(("sendSignOut",))


def test_finish_session_ui_releases_held_prediction_state():
    coordinator = recycle_flow_module.RecycleFlowCoordinator()
    serial = FakeSerial()
    camera_events = []

    coordinator.serial = serial
    coordinator.showCameraRequested.connect(lambda: camera_events.append("camera"))

    coordinator._def_pred_image = "capture.jpg"
    coordinator._cleanup_path = ""
    coordinator._prediction_waiting_for_clear = True
    coordinator._holding_capture_until_completion = True
    coordinator._set_processing_item(True)

    coordinator.finishSessionUi()

    assert ("sendSignOut",) in serial.calls
    assert coordinator._prediction_waiting_for_clear is False
    assert coordinator._holding_capture_until_completion is False
    assert coordinator._processing_item is False
    assert camera_events == ["camera"]


def test_phone_finish_request_completes_ui_without_waiting_for_server():
    coordinator = recycle_flow_module.RecycleFlowCoordinator()
    results = []

    coordinator._def_pred_image = "capture.jpg"
    coordinator._cleanup_path = ""
    coordinator._prediction_waiting_for_clear = True
    coordinator._holding_capture_until_completion = True
    coordinator._set_processing_item(True)
    coordinator.phoneFinishResultRequested.connect(lambda is_pending: results.append(is_pending))

    coordinator.onPhoneFinishRequested("0123456789", 2, 1)

    assert results == [True]
    assert coordinator._waiting_phone_finish_response is False
    assert coordinator._prediction_waiting_for_clear is False
    assert coordinator._holding_capture_until_completion is False
    assert coordinator._processing_item is False
