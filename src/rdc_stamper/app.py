import sys
import os
import fitz
from PIL import Image
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QFileDialog, QGraphicsView, QGraphicsScene, 
                               QGraphicsTextItem, QLineEdit, QCheckBox, QFrame, QGraphicsPixmapItem,
                               QColorDialog, QProgressBar, QMessageBox, QGraphicsItem, QTextEdit, QScrollArea)
from PySide6.QtCore import Qt, Slot, QPointF, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QPixmap, QImage, QPainter, QBrush, QPen, QIcon

from stamper_engine import StamperEngine, build_targets_from_df


def resource_path(*parts):
    """Return an application resource path in source and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, *parts)

# --- STYLES ---
DARK_STYLESHEET = """
QMainWindow { background-color: #121212; }
QWidget { color: #E0E0E0; font-family: 'Segoe UI', sans-serif; font-size: 14px; }

/* Sidebar */
QFrame#sidebar { background-color: #1E1E1E; border-right: 1px solid #333; }
QLabel#header { font-size: 22px; font-weight: bold; color: #2FA572; margin-bottom: 10px; }
QLabel#section { font-size: 11px; font-weight: bold; color: #888; margin-top: 15px; margin-bottom: 5px; }

/* Buttons */
QPushButton {
    background-color: #2D2D2D;
    border: 1px solid #3E3E3E;
    border-radius: 6px;
    padding: 8px 16px;
    color: #FFF;
}
QPushButton:hover { background-color: #383838; border-color: #4E4E4E; }
QPushButton:pressed { background-color: #252525; }
QPushButton:disabled { background-color: #1A1A1A; color: #555; border-color: #222; }

QPushButton#primary { background-color: #2FA572; border: none; font-weight: bold; font-size: 15px; }
QPushButton#primary:hover { background-color: #36BD82; }
QPushButton#primary:pressed { background-color: #278C60; }
QPushButton#stop { background-color: #A52F2F; border: none; font-weight: bold; }
QPushButton#stop:hover { background-color: #C93A3A; }

/* Inputs */
QLineEdit, QTextEdit {
    background-color: #252525;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 6px;
    color: #FFF;
    selection-background-color: #2FA572;
}
QLineEdit:focus, QTextEdit:focus { border-color: #2FA572; }

/* Checkbox */
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #555; border-radius: 3px; background: #252525; }
QCheckBox::indicator:checked { background: #2FA572; border-color: #2FA572; }

/* Canvas/View */
QGraphicsView {
    background-color: #181818;
    border: none;
}

/* Status Bar */
QFrame#statusbar { background-color: #1A1A1A; border-top: 1px solid #333; }
QProgressBar {
    border: none;
    background: #333;
    border-radius: 2px;
    height: 4px;
    text-align: center;
}
QProgressBar::chunk { background-color: #2FA572; }

/* Message Box Override */
QMessageBox { background-color: #FFFFFF; }
QMessageBox QLabel { color: #000000; font-weight: normal; }
QMessageBox QPushButton { 
    background-color: #F0F0F0; 
    color: #000000; 
    border: 1px solid #CCCCCC; 
    border-radius: 4px; 
    padding: 6px 12px;
}
QMessageBox QPushButton:hover { background-color: #E0E0E0; }
"""

class DraggableText(QGraphicsTextItem):
    def __init__(self, text=""):
        super().__init__(text)
        self.setDefaultTextColor(QColor("#000000"))
        # Make it draggable
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFont(QFont("Arial", 12, QFont.Bold))

    def update_style(self, text, color, fs):
        self.setPlainText(text)
        self.setDefaultTextColor(color)
        f = self.font()
        f.setPointSize(int(fs))  # Visual size
        # f.setBold(True) # Already bold in init
        self.setFont(f)

    def set_locked(self, locked):
        if locked:
            self.setFlags(QGraphicsItem.GraphicsItemFlag(0)) # Disable all flags (selection/moving)
        else:
            self.setFlag(QGraphicsItem.ItemIsMovable)
            self.setFlag(QGraphicsItem.ItemIsSelectable)

class ModernStamperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RDC Stamper V2 [Modern]")
        self.setWindowIcon(QIcon(resource_path("app_icon.ico")))
        self.resize(1400, 900)
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(DARK_STYLESHEET)
        
        # Logic Engine
        self.engine = StamperEngine()
        self.engine.signals.update_status.connect(self.update_status)
        self.engine.signals.progress_total.connect(self.set_progress_max)
        self.engine.signals.progress_value.connect(self.set_progress_val)
        self.engine.signals.finished.connect(self.on_finished)
        self.engine.signals.error.connect(self.on_error)
        self.engine.signals.match_found.connect(self.on_match)
        
        # State
        self.pdf_path = None
        self.excel_data = None
        self.targets = {}            # {invoice_no: [{"date":...}]}
        self.page_pixmap_width = 1
        self.page_pixmap_height = 1
        self.stamp_color = QColor("#000000")
        
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- SIDEBAR ---
        # --- SIDEBAR ---
        sidebar_widget = QFrame()
        sidebar_widget.setObjectName("sidebar")
        # fit width is handled by scroll area
        side_layout = QVBoxLayout(sidebar_widget)
        side_layout.setContentsMargins(20, 25, 20, 25)
        side_layout.setSpacing(15)

        # Header
        lbl_title = QLabel("🚛 RDC STAMPER")
        lbl_title.setObjectName("header")
        side_layout.addWidget(lbl_title)

        # 1. File Selection
        side_layout.addWidget(self.section_label("1. FILE SELECTION"))
        
        self.btn_load_pdf = QPushButton("Load PDF Document")
        self.btn_load_pdf.clicked.connect(self.load_pdf)
        self.btn_load_pdf.setFixedHeight(40)
        side_layout.addWidget(self.btn_load_pdf)

        self.btn_load_excel = QPushButton("Load Excel List")
        self.btn_load_excel.clicked.connect(self.load_excel)
        self.btn_load_excel.setFixedHeight(40)
        side_layout.addWidget(self.btn_load_excel)
        
        self.lbl_file_info = QLabel("No files loaded")
        self.lbl_file_info.setStyleSheet("color: #666; font-size: 12px;")
        side_layout.addWidget(self.lbl_file_info)

        # 2. Text Content
        side_layout.addWidget(self.section_label("2. TEXT CONTENT"))
        
        self.txt_stamp = QTextEdit()
        self.txt_stamp.setPlainText("APPROVED FOR PAYMENT")
        self.txt_stamp.setFixedHeight(80)
        self.txt_stamp.textChanged.connect(self.update_preview_text)
        side_layout.addWidget(self.txt_stamp)

        # Style Row
        style_row = QHBoxLayout()
        style_row.setSpacing(10) 
        
        lbl_size = QLabel("Size:")
        lbl_size.setStyleSheet("margin-top: 2px;") # Slight visual tweak
        style_row.addWidget(lbl_size)
        
        self.inp_fs = QLineEdit("12")
        self.inp_fs.setFixedSize(50, 32) # Fixed dimensions
        self.inp_fs.setAlignment(Qt.AlignCenter)
        self.inp_fs.textChanged.connect(self.update_preview_text)
        style_row.addWidget(self.inp_fs)

        self.btn_color = QPushButton("Color")
        self.btn_color.setFixedSize(80, 32)
        self.btn_color.setStyleSheet(f"background-color: {self.stamp_color.name()}; margin-left: 10px; border: none; border-radius: 4px;")
        self.btn_color.clicked.connect(self.choose_color)
        style_row.addWidget(self.btn_color)
        
        style_row.addStretch() # Push to left
        side_layout.addLayout(style_row)

        # 3. Settings
        side_layout.addWidget(self.section_label("3. SETTINGS"))
        
        self.chk_skip = QCheckBox("Skip Blank Pages")
        side_layout.addWidget(self.chk_skip)
        
        self.chk_ocr = QCheckBox("Enable OCR (Slower)")
        self.chk_ocr.setChecked(True)
        side_layout.addWidget(self.chk_ocr)

        self.chk_match_dates = QCheckBox("Match Dates")
        self.chk_match_dates.setChecked(False)
        side_layout.addWidget(self.chk_match_dates)

        side_layout.addStretch()

        # Actions
        self.btn_start = QPushButton("START STAMPING")
        self.btn_start.setObjectName("primary")
        self.btn_start.setFixedHeight(55)
        self.btn_start.clicked.connect(self.start_processing)
        side_layout.addWidget(self.btn_start)

        side_layout.addSpacing(10) # Explicit gap

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.engine.cancel)
        side_layout.addWidget(self.btn_stop)

        # Reset Button
        self.btn_reset = QPushButton("RESET APP")
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #444444; 
                color: #FFFFFF;
                border: 1px solid #666; 
                border-radius: 4px;
                padding: 8px;
                margin-top: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #555555; }
        """)
        self.btn_reset.clicked.connect(self.reset_app_state)
        side_layout.addWidget(self.btn_reset)

        # Footer
        lbl_footer = QLabel("Made with <3 by Jarjish")
        lbl_footer.setAlignment(Qt.AlignCenter)
        lbl_footer.setStyleSheet("color: #555; font-size: 10px; margin-top: 10px;")
        side_layout.addWidget(lbl_footer)

        # Scroll Area Wrapper
        scroll_area = QScrollArea()
        scroll_area.setWidget(sidebar_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(380) # Fixed width for the pane
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Match background to sidebar for seamless look
        scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #1E1E1E; }
            QScrollBar:vertical {
                border: none;
                background: #2D2D2D;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        main_layout.addWidget(scroll_area)

        # --- CANVAS AREA ---
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor("#181818")))
        
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.TextAntialiasing)
        content_layout.addWidget(self.view)

        # Status Bar
        self.status_bar = QFrame()
        self.status_bar.setObjectName("statusbar")
        self.status_bar.setFixedHeight(30)
        stat_box = QHBoxLayout(self.status_bar)
        stat_box.setContentsMargins(10, 0, 10, 0)
        
        self.lbl_status = QLabel("Ready")
        stat_box.addWidget(self.lbl_status)
        
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        # self.progress.setVisible(False)
        stat_box.addStretch()
        stat_box.addWidget(self.progress)
        
        content_layout.addWidget(self.status_bar)

        main_layout.addLayout(content_layout)

        # Init Scene Items
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        self.stamp_item = DraggableText("APPROVED FOR PAYMENT")
        self.scene.addItem(self.stamp_item)
        self.stamp_item.setPos(100, 100)

    # --- HELPERS ---
    def section_label(self, text):
        l = QLabel(text)
        l.setObjectName("section")
        return l

    def update_preview_text(self):
        txt = self.txt_stamp.toPlainText()
        try: fs = float(self.inp_fs.text())
        except: fs = 12.0
        
        # Visual Helper: In the real PDF, '12' is 12 points.
        # On Screen, we need to scale it relative to the image size to look accurate.
        # Current logic matches 'visual' size.
        # We will use a scaling factor if we want, but for now direct point size is fine for preview relative to image.
        
        self.stamp_item.update_style(txt, self.stamp_color, fs)

    def choose_color(self):
        c = QColorDialog.getColor(self.stamp_color, self, "Choose Stamp Color")
        if c.isValid():
            self.stamp_color = c
            self.btn_color.setStyleSheet(f"background-color: {c.name()}; margin-left: 10px;")
            self.update_preview_text()

    def load_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Excel", "", "Excel/CSV (*.xlsx *.xls *.csv)")
        if not path: return
        
        df = self.engine.load_excel(path)
        if df is not None:
            self.excel_data = df
            targets, total_rows, dup_rows = build_targets_from_df(df)
            self.targets = targets
            inv_count = sum(len(v) for v in targets.values())
            dup_info  = f" ({dup_rows} dupes removed)" if dup_rows > 0 else ""
            self.lbl_status.setText(f"Loaded: {inv_count} invoices{dup_info}")
            self.lbl_file_info.setText(
                f"{os.path.basename(path)}\n"
                f"{inv_count} invoices loaded{dup_info}"
            )
        else:
            self.targets = {}

    def load_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PDF", "", "PDF Files (*.pdf)")
        if not paths: return
        
        if len(paths) > 1:
            self.lbl_status.setText("Merging...")
            self.lbl_file_info.setText("Merging...")
            QApplication.processEvents() # Force UI Update
            
            # Use QTimer to allow UI to paint before blocking operation (Simple "Async")
            # Or just call it. Since engine.merge_pdfs catches errors, we check result.
            
            try:
                merged_path = self.engine.merge_pdfs(paths)
                if merged_path:
                    self.pdf_path = merged_path
                    self.lbl_file_info.setText(f"Merged {len(paths)} files")
                    self.render_pdf_preview()
                else:
                    QMessageBox.critical(self, "Merge Error", "Failed to merge files. Check logs.")
                    self.lbl_status.setText("Merge Failed")
                    self.lbl_file_info.setText("Error")
            except Exception as e:
                 QMessageBox.critical(self, "Error", f"Merge Exception: {e}")
        else:
            self.pdf_path = paths[0]
            self.lbl_file_info.setText(os.path.basename(self.pdf_path))
            self.render_pdf_preview()

    def render_pdf_preview(self):
        if not self.pdf_path: return
        
        try:
            doc = fitz.open(self.pdf_path)
            page = doc[0]
            # FORCE RGB for QImage compatibility
            pix = page.get_pixmap(colorspace=fitz.csRGB) 
            
            img_data = pix.samples
            # Ensure stride is correct
            qimg = QImage(img_data, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            
            self.pixmap_item.setPixmap(pixmap)
            self.scene.setSceneRect(0, 0, pix.width, pix.height)
            self.img_width = pix.width
            self.img_height = pix.height
            
            doc.close()
            self.lbl_status.setText("Preview Loaded")
        except Exception as e:
            QMessageBox.critical(self, "Preview Error", f"Could not render preview: {e}")

    def start_processing(self):
        if not self.pdf_path:
            QMessageBox.warning(self, "No PDF", "Please load a PDF first.")
            return
            
        # Get Save Path
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Result", "", "PDF Files (*.pdf)")
        if not save_path: return

        # Validate Targets
        if not self.targets:
            reply = QMessageBox.question(self, "Stamp All?", 
                                         "No Excel targets found. Stamp ALL pages?\n(Blank pages will still be skipped)",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No: return
        
        # Lock UI Stamp
        self.stamp_item.set_locked(True)

        # Get Text Geometry
        pos = self.stamp_item.pos()
        rel_x = pos.x() / self.img_width
        rel_y = pos.y() / self.img_height
        
        try: fs = float(self.inp_fs.text())
        except: fs = 12
        
        c = self.stamp_color
        rgb = (c.red()/255, c.green()/255, c.blue()/255)

        config = {
            "pdf_path": self.pdf_path,
            "save_path": save_path,
            "targets": self.targets,
            "skip_blank": self.chk_skip.isChecked(),
            "ocr_enabled": self.chk_ocr.isChecked(),
            "match_dates": self.chk_match_dates.isChecked(),
            "text_data": {
                "content": self.txt_stamp.toPlainText(),
                "fs": fs,
                "color": rgb,
                "rel_x": rel_x,
                "rel_y": rel_y
            }
        }
        
        # UI State
        self.btn_start.setEnabled(False); self.btn_load_pdf.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        
        self.engine.start_processing(config)

    # --- SLOTS ---
    @Slot(str)
    def update_status(self, text):
        self.lbl_status.setText(text)

    @Slot(int)
    def set_progress_max(self, val):
        self.progress.setMaximum(val)

    @Slot(int)
    def set_progress_val(self, val):
        self.progress.setValue(val)

    @Slot(str)
    def on_finished(self, msg):
        self.reset_ui()
        QMessageBox.information(self, "Done", msg)
        
        # Ask to reset
        reply = QMessageBox.question(self, "New Batch?", "Job Complete. Do you want to reset the app for a new batch?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.reset_app_state()

    @Slot(str)
    def on_error(self, msg):
        self.reset_ui()
        QMessageBox.critical(self, "Error", msg)

    @Slot(int, str)
    def on_match(self, count, text):
        pass # Optional: Show live match feed

    def reset_ui(self):
        self.stamp_item.set_locked(False)
        self.btn_start.setEnabled(True); self.btn_load_pdf.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setValue(0)
        self.lbl_status.setText("Ready")

    def reset_app_state(self):
        # 1. Cleanup Temp File
        if self.pdf_path and os.path.basename(self.pdf_path).startswith("_merged_temp_"):
            try:
                os.remove(self.pdf_path)
            except Exception as e:
                print(f"Cleanup error: {e}")

        # 2. Clear Data
        self.pdf_path = None
        self.excel_data = None
        self.targets = {}
        
        # 2. Reset Text
        self.txt_stamp.setPlainText("APPROVED FOR PAYMENT")
        self.inp_fs.setText("12")
        self.stamp_color = QColor("#000000")
        self.btn_color.setStyleSheet(f"background-color: {self.stamp_color.name()}; margin-left: 10px; border: none; border-radius: 4px;")
        
        # 3. Clear Preview
        self.pixmap_item.setPixmap(QPixmap())
        self.scene.setSceneRect(0, 0, 100, 100) # Reset to small default
        self.stamp_item.setPos(50, 50)
        self.stamp_item.update_style("APPROVED FOR PAYMENT", self.stamp_color, 12)
        
        # 4. Reset Labels
        self.lbl_file_info.setText("No files loaded")
        self.lbl_status.setText("App Reset")
        self.progress.setValue(0)
        
        # 5. UI State
        self.btn_start.setEnabled(True)
        self.btn_load_pdf.setEnabled(True)
        self.btn_stop.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RDC Stamper V2")
    app.setApplicationDisplayName("RDC Stamper V2")
    app.setOrganizationName("RDC")
    app.setWindowIcon(QIcon(resource_path("app_icon.ico")))
    
    # Optional: Font fix for high DPI
    # app.setAttribute(Qt.AA_EnableHighDpiScaling)
    
    window = ModernStamperApp()
    window.showMaximized()
    sys.exit(app.exec())
