from PySide6.QtCore import QLoggingCategory, qCCritical, qCDebug, qCInfo, qCWarning

class Logger:
    def __init__(self, logging_category: QLoggingCategory) -> None:
        self.logging_category = logging_category

    def critical(self, message: str) -> None:
        qCCritical(self.logging_category, message)

    def debug(self, message: str) -> None:
        qCDebug(self.logging_category, message)

    def info(self, message: str) -> None:
        qCInfo(self.logging_category, message)

    def warning(self, message: str) -> None:
        qCWarning(self.logging_category, message)


def getLogger(category: str) -> Logger:
    return Logger(QLoggingCategory(category))
