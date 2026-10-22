"""Тёмная тема с нейтральными поверхностями и одним акцентом."""
DARK_THEME_QSS = """
QWidget { font-family: Onest, 'Segoe UI'; font-size: 16px; color: #f0f0f2; }
QMainWindow, QDialog, QWidget#centralWidget { background: #18181b; }
QLabel { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #18181b; border: none; }
QWidget#serviceCard { background: #232326; border: 1px solid #353539; border-radius: 14px; }
QPushButton, QToolButton { background: #232326; border: 1px solid #424248; border-radius: 8px; padding: 9px 13px; min-height: 22px; }
QPushButton:hover, QToolButton:hover { background: #303035; border-color: #686870; }
QPushButton:pressed, QToolButton:pressed { background: #35353b; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus { border: 2px solid #397fe8; }
QPushButton:disabled, QToolButton:disabled { color: #888890; background: #29292d; }
QPushButton[class='primaryBtn'] { background: #397fe8; color: white; border-color: #397fe8; font-weight: 600; }
QPushButton[class='primaryBtn']:hover { background: #4d8def; }
QPushButton[class='primaryBtn']:disabled { background: #354965; border-color: #354965; }
QLineEdit, QComboBox, QSpinBox { background: #232326; border: 1px solid #424248; border-radius: 8px; padding: 9px 12px; selection-background-color: #397fe8; }
QTabWidget::pane { border: none; padding-top: 10px; }
QTabBar::tab { background: #232326; padding: 9px 18px; border: none; border-radius: 7px; margin-right: 4px; color: #aaaab2; }
QTabBar::tab:selected { background: #232326; color: #f0f0f2; }
QProgressBar { border: none; background: #303035; border-radius: 5px; min-height: 22px; text-align: center; font-size: 14px; }
QProgressBar::chunk { background: #365d8d; border-radius: 5px; }
QGroupBox { border: 1px solid #35353b; border-radius: 10px; margin-top: 14px; padding: 16px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; }
QCheckBox { spacing: 10px; padding: 5px 0; }
QCheckBox::indicator { width: 19px; height: 19px; background: #232326; border: 1px solid #777780; border-radius: 4px; }
QCheckBox::indicator:checked { background: #397fe8; border-color: #397fe8; image: url(__CHECK_ICON__); }
QCheckBox::indicator:disabled { border-color: #424248; background: #29292d; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url(__CHEVRON_ICON__); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: #232326; color: #f0f0f2; border: 1px solid #424248; selection-background-color: #293a52; }
QMessageBox { background: #18181b; }
QTabBar::tab:selected { background: #35353b; }
QToolButton:hover { background: #35353b; }
QListWidget { background: #232326; border: 1px solid #35353b; border-radius: 8px; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: #55555d; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QToolTip { color: #f0f0f2; background: #232326; border: 1px solid #424248; padding: 8px; }
QMenu { background: #232326; padding: 6px; border: 1px solid #35353b; }
QMenu::item { padding: 8px 18px; }
QMenu::item:selected { background: #293a52; color: #99c0fa; }
"""


def apply_dark_palette(app):
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    for role, color in {
        QPalette.Window: '#18181b', QPalette.WindowText: '#f0f0f2',
        QPalette.Base: '#232326', QPalette.AlternateBase: '#29292d',
        QPalette.Text: '#f0f0f2', QPalette.Button: '#232326',
        QPalette.ButtonText: '#f0f0f2', QPalette.Highlight: '#397fe8',
        QPalette.HighlightedText: '#ffffff', QPalette.ToolTipBase: '#232326',
        QPalette.ToolTipText: '#f0f0f2', QPalette.PlaceholderText: '#aaaab2',
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(DARK_THEME_QSS)

from pathlib import Path
_ASSETS = Path(__file__).resolve().parents[1] / 'assets'
DARK_THEME_QSS = DARK_THEME_QSS.replace('__CHECK_ICON__', (_ASSETS / 'check.svg').as_posix()).replace('__CHEVRON_ICON__', (_ASSETS / 'chevron.svg').as_posix())
