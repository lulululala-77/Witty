"""Quiet, light desktop surfaces shared by the assistant's pages."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSpinBox
from qfluentwidgets import (
    ComboBox, HyperlinkButton, LineEdit, PlainTextEdit, PrimaryPushButton, PushButton,
    TransparentToolButton, setCustomStyleSheet,
)

TEXT = "#24262b"
MUTED = "#767b85"
ACCENT = "#4775bd"


def paint_window(widget):
    """Rounded pearl surface. Painted locally, so it also works without OS blur."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(8, 8, -8, -8)
    painter.setPen(Qt.NoPen)
    for spread in range(7, 0, -1):
        painter.setBrush(QColor(35, 42, 63, 3))
        painter.drawRoundedRect(rect.adjusted(-spread, -spread + 2, spread, spread + 2),
                                26 + spread, 26 + spread)
    path = QPainterPath()
    path.addRoundedRect(rect, 26, 26)
    painter.fillPath(path, QColor("#f4f4f7"))
    painter.setClipPath(path)
    # Very soft lavender and cool-blue light, like a frosted desktop panel.
    for x, y, radius, color in (
        (0.05, 0.03, 0.95, QColor(224, 218, 242, 95)),
        (1.0, 0.35, 1.05, QColor(219, 232, 249, 80)),
        (0.1, 1.0, 0.9, QColor(229, 238, 232, 70)),
    ):
        glow = QRadialGradient(widget.width() * x, widget.height() * y, widget.width() * radius)
        glow.setColorAt(0, color)
        glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        painter.fillPath(path, glow)
    painter.setClipping(False)
    painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, 26, 26)


def paint_surface(widget, accent=False):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
    fill.setColorAt(0, QColor(255, 255, 255, 225 if accent else 190))
    fill.setColorAt(1, QColor(236, 242, 252, 210) if accent else QColor(255, 255, 255, 135))
    painter.setBrush(fill)
    painter.setPen(QPen(QColor(139, 165, 205, 100) if accent else QColor(255, 255, 255, 235), 1))
    painter.drawRoundedRect(rect, 18, 18)


def style_control(widget):
    """Keep Fluent behavior/accessibility; replace only its visual treatment."""
    if isinstance(widget, TransparentToolButton):
        qss = """
            TransparentToolButton { border: none; border-radius: 10px; background: transparent; }
            TransparentToolButton:hover { background: rgba(70, 78, 100, 18); }
            TransparentToolButton:pressed { background: rgba(70, 78, 100, 30); }
            TransparentToolButton:focus { border: 1px solid #8ba9d6; }
        """
    elif isinstance(widget, HyperlinkButton):
        qss = """
            HyperlinkButton { background: transparent; color: #4775bd; border: none;
                border-radius: 8px; padding: 0px 8px; }
            HyperlinkButton:hover { background: rgba(71, 117, 189, 15); }
            HyperlinkButton:focus { border: 1px solid #8ba9d6; }
        """
    elif isinstance(widget, QSpinBox):
        # Native spin layout keeps its editor visible on Qt 6.12 as well.
        widget.setStyleSheet("""
            QSpinBox { background: rgba(255, 255, 255, 185); color: #343740;
                border: 1px solid rgba(95, 106, 126, 30); border-radius: 10px;
                padding: 0px 32px 0px 10px; selection-background-color: #dce8fa; }
            QSpinBox:focus { border-color: #8ba9d6; background: white; }
            QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border;
                width: 24px; height: 14px; border: none; background: transparent; margin-right: 5px; }
            QSpinBox::up-button { subcontrol-position: top right; margin-top: 3px; }
            QSpinBox::down-button { subcontrol-position: bottom right; margin-bottom: 3px; }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #edf0f5; border-radius: 4px; }
            QSpinBox::up-arrow, QSpinBox::down-arrow { width: 10px; height: 8px; }
            QSpinBox::up-arrow { image: url(:/qfluentwidgets/images/spin_box/Up_black.svg); }
            QSpinBox::down-arrow { image: url(:/qfluentwidgets/images/spin_box/Down_black.svg); }
        """)
        return
    elif isinstance(widget, PrimaryPushButton):
        qss = """
            PrimaryPushButton { background: #4775bd; color: white; border: 1px solid #4775bd;
                border-radius: 10px; padding: 7px 16px; }
            PrimaryPushButton:hover { background: #3d68ac; border-color: #3d68ac; }
            PrimaryPushButton:pressed { background: #345d9e; }
            PrimaryPushButton:disabled { background: #e2e5eb; border-color: #e2e5eb; color: #9298a2; }
            PrimaryPushButton:focus { border: 1px solid #244e91; }
        """
    elif isinstance(widget, (PushButton, ComboBox)):
        qss = """
            PushButton, ComboBox { background: rgba(255, 255, 255, 185); color: #343740;
                border: 1px solid rgba(95, 106, 126, 28); border-radius: 10px; padding: 7px 13px; }
            ComboBox { padding-right: 30px; text-align: left; }
            PushButton:hover, ComboBox:hover { background: #ffffff; border-color: #ccd3df; }
            PushButton:pressed, ComboBox:pressed { background: #edf0f5; }
            PushButton:disabled, ComboBox:disabled { color: #999ea7; background: #eff0f3; }
            PushButton:focus, ComboBox:focus { border: 1px solid #8ba9d6; }
        """
    elif isinstance(widget, (LineEdit, PlainTextEdit)):
        qss = """
            LineEdit, PlainTextEdit { background: rgba(255, 255, 255, 185); color: #343740;
                border: 1px solid rgba(95, 106, 126, 30); border-radius: 10px;
                padding: 7px 10px; selection-background-color: #dce8fa; selection-color: #24262b; }
            LineEdit:hover, PlainTextEdit:hover { border-color: #cbd2de; }
            LineEdit:focus, PlainTextEdit:focus { background: #ffffff; border-color: #8ba9d6; }
            LineEdit:disabled, PlainTextEdit:disabled { color: #999ea7; background: #eff0f3; }
        """
    else:
        return
    setCustomStyleSheet(widget, qss, qss)


NAV_STYLE = """
    QFrame#pageNavigation { background: rgba(95, 106, 126, 16); border: 1px solid rgba(95, 106, 126, 12);
        border-radius: 13px; }
    QPushButton { border: 1px solid transparent; border-radius: 10px; background: transparent;
        color: #797e88; padding: 7px 12px; font-size: 13px; }
    QPushButton:hover { color: #343740; background: rgba(255, 255, 255, 100); }
    QPushButton:checked { background: rgba(255, 255, 255, 235); color: #24262b;
        border: 1px solid rgba(255, 255, 255, 240); font-weight: 600; }
    QPushButton:focus { border: 1px solid #8ba9d6; }
"""
