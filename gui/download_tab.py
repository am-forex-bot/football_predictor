"""Download tab — league selection, data download, status table, cleanup."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QTextEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

from core.leagues import COUNTRIES, get_current_season_code, get_league_info, season_display
from core.downloader import DownloadWorker
from core.cleaner import process_and_save
from core.data_manager import (
    get_workbook_path, record_download, get_all_downloads,
    clean_league, clean_stale, clean_all, is_stale,
)


class DownloadTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._thread = None
        self._worker = None
        self._init_ui()
        self._refresh_status_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- League selection ---
        select_group = QGroupBox("League Selection")
        select_layout = QHBoxLayout(select_group)

        select_layout.addWidget(QLabel("Country:"))
        self.country_combo = QComboBox()
        self.country_combo.addItems(COUNTRIES.keys())
        self.country_combo.currentTextChanged.connect(self._on_country_changed)
        select_layout.addWidget(self.country_combo)

        select_layout.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        select_layout.addWidget(self.league_combo)

        select_layout.addWidget(QLabel("Seasons:"))
        self.seasons_spin = QSpinBox()
        self.seasons_spin.setRange(1, 10)
        self.seasons_spin.setValue(8)
        self.seasons_spin.setToolTip(
            "Number of seasons to download.\n"
            "More seasons = more thorough backtest.\n"
            "1 = current season only, 5 = last 5 seasons."
        )
        select_layout.addWidget(self.seasons_spin)

        season = get_current_season_code()
        sd = season_display(season)
        select_layout.addWidget(QLabel(f"Current: {sd}"))
        select_layout.addStretch()

        layout.addWidget(select_group)

        # Populate initial leagues
        self._on_country_changed(self.country_combo.currentText())

        # --- Action buttons ---
        btn_layout = QHBoxLayout()

        self.download_btn = QPushButton("Download Selected League")
        self.download_btn.clicked.connect(self._on_download)
        btn_layout.addWidget(self.download_btn)

        self.download_all_btn = QPushButton("Download All Leagues")
        self.download_all_btn.clicked.connect(self._on_download_all)
        btn_layout.addWidget(self.download_all_btn)

        btn_layout.addStretch()

        self.clean_stale_btn = QPushButton("Clean Stale Data")
        self.clean_stale_btn.setProperty("danger", True)
        self.clean_stale_btn.clicked.connect(self._on_clean_stale)
        btn_layout.addWidget(self.clean_stale_btn)

        self.clean_all_btn = QPushButton("Clean All Data")
        self.clean_all_btn.setProperty("danger", True)
        self.clean_all_btn.clicked.connect(self._on_clean_all)
        btn_layout.addWidget(self.clean_all_btn)

        layout.addLayout(btn_layout)

        # --- Progress bar ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # --- Log ---
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        log_layout.addWidget(self.log)
        layout.addWidget(log_group)

        # --- Status table ---
        status_group = QGroupBox("Downloaded Data")
        status_layout = QVBoxLayout(status_group)
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(7)
        self.status_table.setHorizontalHeaderLabels([
            "League", "Downloaded", "Results", "Backtest", "Seasons", "Status", "Actions",
        ])
        self.status_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.status_table.setAlternatingRowColors(True)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.status_table.verticalHeader().setVisible(False)
        status_layout.addWidget(self.status_table)
        layout.addWidget(status_group)

    # ---- Signals / slots ----

    def _on_country_changed(self, country: str):
        self.league_combo.clear()
        leagues = COUNTRIES.get(country, {})
        self.league_combo.addItems(leagues.keys())

    def _log(self, msg: str, color: str = "#cdd6f4"):
        self.log.append(f'<span style="color:{color}">{msg}</span>')

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.download_btn.setEnabled(not busy)
        self.download_all_btn.setEnabled(not busy)

    def _on_download(self):
        country = self.country_combo.currentText()
        league = self.league_combo.currentText()
        info = get_league_info(country, league)
        if not info:
            return
        n_seasons = self.seasons_spin.value()
        self._start_download(info["code"], f"{league} ({country})", n_seasons=n_seasons)

    def _on_download_all(self):
        # Collect all league codes
        n_seasons = self.seasons_spin.value()
        self._all_queue = []
        for country, leagues in COUNTRIES.items():
            for league_name, info in leagues.items():
                self._all_queue.append((info["code"], f"{league_name} ({country})", n_seasons))
        self._download_next_in_queue()

    def _download_next_in_queue(self):
        if not self._all_queue:
            self._set_busy(False)
            self._log("All downloads complete!", "#22c55e")
            self.main_window.set_status("All downloads complete")
            return
        code, name, n_seasons = self._all_queue.pop(0)
        self._start_download(code, name, chain=True, n_seasons=n_seasons)

    def _start_download(self, code: str, display_name: str, chain: bool = False,
                        n_seasons: int = 1):
        self._set_busy(True)
        self._current_code = code
        self._current_name = display_name
        self._chain = chain
        seasons_txt = f" ({n_seasons} seasons)" if n_seasons > 1 else ""
        self._log(f"Starting download: {display_name}{seasons_txt}...")

        self._thread = QThread()
        self._worker = DownloadWorker(code, n_seasons=n_seasons)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda msg: self._log(msg))
        self._worker.finished.connect(self._on_download_finished)
        self._worker.error.connect(self._on_download_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

    def _on_download_finished(self, data: dict):
        code = self._current_code
        name = self._current_name

        try:
            results_df = data["results"]
            fixtures_df = data.get("fixtures")  # from dedicated fixtures.csv
            season_data = data.get("season_data")  # multi-season: [(code, df), ...]
            output = get_workbook_path(code)
            summary = process_and_save(results_df, fixtures_df, output,
                                       season_data=season_data)
            record_download(code, name, summary["results_count"],
                            summary["fixtures_count"], summary["teams"],
                            backtest_matches=summary.get("backtest_matches", 0),
                            n_seasons=summary.get("n_seasons", 1))

            bt_info = ""
            if summary.get("n_seasons", 1) > 1:
                bt_info = (f", backtest: {summary['backtest_matches']} matches "
                          f"across {summary['n_seasons']} seasons")

            self._log(
                f"Saved {name}: {summary['results_count']} results, "
                f"{summary['fixtures_count']} fixtures, {summary['teams']} teams{bt_info}",
                "#22c55e",
            )
            self.main_window.set_status(f"Downloaded {name}")
        except Exception as exc:
            self._log(f"Error processing {name}: {exc}", "#ef4444")

        self._refresh_status_table()

        if self._chain:
            self._download_next_in_queue()
        else:
            self._set_busy(False)

    def _on_download_error(self, msg: str):
        self._log(f"Error: {msg}", "#ef4444")
        self.main_window.set_status(f"Download failed")

        if self._chain:
            self._download_next_in_queue()
        else:
            self._set_busy(False)

    def _on_clean_stale(self):
        clean_stale()
        self._log("Cleaned stale data.", "#f59e0b")
        self._refresh_status_table()

    def _on_clean_all(self):
        reply = QMessageBox.question(
            self, "Confirm", "Delete ALL downloaded data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            clean_all()
            self._log("All data cleaned.", "#f59e0b")
            self._refresh_status_table()

    def _refresh_status_table(self):
        downloads = get_all_downloads()
        self.status_table.setRowCount(len(downloads))

        for row, (code, info) in enumerate(downloads.items()):
            self.status_table.setItem(row, 0, QTableWidgetItem(info.get("league_name", code)))

            dt_str = info.get("downloaded_at", "")
            try:
                dt = datetime.fromisoformat(dt_str)
                display_dt = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                display_dt = dt_str
            self.status_table.setItem(row, 1, QTableWidgetItem(display_dt))

            self.status_table.setItem(row, 2, QTableWidgetItem(str(info.get("results_count", 0))))
            bt_matches = info.get("backtest_matches", info.get("results_count", 0))
            self.status_table.setItem(row, 3, QTableWidgetItem(str(bt_matches)))
            n_seasons = info.get("n_seasons", 1)
            self.status_table.setItem(row, 4, QTableWidgetItem(str(n_seasons)))

            stale = is_stale(code)
            status_item = QTableWidgetItem("Stale" if stale else "Fresh")
            status_item.setForeground(
                Qt.GlobalColor.red if stale else Qt.GlobalColor.green
            )
            self.status_table.setItem(row, 5, status_item)

            # Delete button
            del_btn = QPushButton("Delete")
            del_btn.setProperty("danger", True)
            del_btn.setFixedHeight(28)
            del_btn.clicked.connect(lambda checked, c=code: self._delete_league(c))
            self.status_table.setCellWidget(row, 6, del_btn)

    def _delete_league(self, code: str):
        clean_league(code)
        self._log(f"Deleted data for {code}.", "#f59e0b")
        self._refresh_status_table()
