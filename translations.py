"""
translations.py — UI string translations for Video Grid Player.

Each entry in TRANSLATIONS is keyed by a language code (e.g. "en", "fr",
"ja") and maps string keys to their translated equivalents.

Adding a new language: add a new top-level key with the same set of string
keys as "en" and provide translated values for each.
"""

LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "zh": "中文（简体）",
    "ja": "日本語",
    "ko": "한국어",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # --- dialog chrome ---
        "section_app":          "Video Grid Player",
        "section_language":     "Language",
        "section_grid":         "Video Grid",
        "section_pages":        "Video Grid Pages",
        "section_player":       "Player",
        "dialog_title":         "Open Videos",
        "app_title":            "Video Grid Player",
        "app_desc":             "Select a folder containing your video files.\nYour videos will be shown in the grid configured below.",

        # --- language row ---
        "language_label":       "Language:",
        "translate_titles":    "Attempt to translate video titles into the selected language",

        # --- grid size ---
        "rows_label":           "Rows:",
        "cols_label":           "Columns:",

        # --- thumbnail quality ---
        "thumb_quality_label":  "Thumbnail quality:",
        "thumb_standard":       "Standard (360p)",
        "thumb_high":           "High (720p)",
        "thumb_ultra":          "Ultra (1080p)",

        # --- checkboxes ---
        "show_titles":          "Show video titles in the grid",
        "full_width":           "Full-width layout (no gaps between videos)",
        "use_sidecar":          "Use matching image files as thumbnails (e.g. video.jpg next to video.mp4)",
        "clip_thumb":           "Preserve thumbnail aspect ratio (clip to fit instead of stretching)",
        "show_set_thumb_btn":   "Show “Set Thumbnail” button while a video is playing",
        "auto_hide":            "Auto-hide on-screen controls after 5 seconds of playback",
        "chevron_hides_close":  "Chevron button also hides the close (✕) button",
        "shuffle":              "Shuffle — play a random video when the current one ends",
        "multi_page":           "Multiple pages — show all videos across multiple grid pages",
        "page_fill_label":     "When videos don't fill a page evenly:",
        "page_fill_blank":     "Allow blank spaces",
        "page_fill_round_up":  "Round up the number of pages",
        "page_fill_wrap":      "Fill empty spaces with previously shown videos",

        # --- buttons ---
        "choose_folder":        "Choose Folder…",
        "open_last":            "Open Last Folder",
        "cancel":               "Cancel",

        # --- tooltips / messages ---
        "reopen_tip":           "Reopen {folder}",
        "no_last_folder_tip":   "No previous folder is available yet — use “Choose Folder…” first.",
        "no_videos_title":      "No videos",
        "no_videos_msg":        "No supported video files were found in that folder.\n\nSupported extensions: {exts}",
        "folder_error_title":   "Error",
        "folder_error_msg":     "Could not read folder:\n{error}",

        # --- menu ---
        "menu_file":            "&File",
        "menu_open_folder":     "&Open Folder…",
        "menu_fullscreen":      "Full Screen",
        "menu_quit":            "&Quit",

        # --- overlay tooltips ---
        "close_tip":            "Close video and return to grid (Esc)",
        "thumb_tip":            "Use the current frame as this video’s grid thumbnail",
        "loop_off_tip":         "Loop: off  —  click to enable",
        "loop_on_tip":          "Loop: on  —  click to toggle",
        "loop_tip_fmt":         "Loop: {state}  —  click to toggle",
        "loop_on":              "on",
        "loop_off":             "off",
        "hide_controls_tip":    "Hide on-screen controls",
        "show_controls_tip":    "Show on-screen controls",
    },

    "fr": {
        # --- dialog chrome ---
        "section_app":          "Lecteur en grille",
        "section_language":     "Langue",
        "section_grid":         "Grille vidéo",
        "section_pages":        "Pages de la grille",
        "section_player":       "Lecteur",
        "dialog_title":         "Ouvrir des vidéos",
        "app_title":            "Lecteur en grille",
        "app_desc":             "Sélectionnez un dossier contenant vos fichiers vidéo.\nVos vidéos s’afficheront dans la grille configurée ci-dessous.",

        # --- language row ---
        "language_label":       "Langue :",
        "translate_titles":    "Tenter de traduire les titres des vidéos dans la langue sélectionnée",

        # --- grid size ---
        "rows_label":           "Lignes :",
        "cols_label":           "Colonnes :",

        # --- thumbnail quality ---
        "thumb_quality_label":  "Qualité des miniatures :",
        "thumb_standard":       "Standard (360p)",
        "thumb_high":           "Haute (720p)",
        "thumb_ultra":          "Ultra (1080p)",

        # --- checkboxes ---
        "show_titles":          "Afficher les titres des vidéos dans la grille",
        "full_width":           "Mise en page pleine largeur (sans espaces entre les vidéos)",
        "use_sidecar":          "Utiliser les images associées comme miniatures (ex. vidéo.jpg à côté de vidéo.mp4)",
        "clip_thumb":           "Conserver le format des miniatures (rogner au lieu d’étirer)",
        "show_set_thumb_btn":   "Afficher le bouton « Définir la miniature » pendant la lecture",
        "auto_hide":            "Masquer automatiquement les commandes après 5 secondes de lecture",
        "chevron_hides_close":  "Le bouton chevron masque aussi le bouton fermer (✕)",
        "shuffle":              "Aléatoire — lire une vidéo aléatoire à la fin de la vidéo en cours",
        "multi_page":           "Pages multiples — afficher toutes les vidéos sur plusieurs pages",
        "page_fill_label":     "Quand les vidéos ne remplissent pas une page entière :",
        "page_fill_blank":     "Autoriser les espaces vides",
        "page_fill_round_up":  "Arrondir le nombre de pages",
        "page_fill_wrap":      "Remplir les espaces vides avec les vidéos précédemment affichées",

        # --- buttons ---
        "choose_folder":        "Choisir un dossier…",
        "open_last":            "Ouvrir le dernier dossier",
        "cancel":               "Annuler",

        # --- tooltips / messages ---
        "reopen_tip":           "Réouvrir {folder}",
        "no_last_folder_tip":   "Aucun dossier précédent disponible — utilisez d’abord « Choisir un dossier… ».",
        "no_videos_title":      "Aucune vidéo",
        "no_videos_msg":        "Aucun fichier vidéo compatible n’a été trouvé dans ce dossier.\n\nExtensions prises en charge : {exts}",
        "folder_error_title":   "Erreur",
        "folder_error_msg":     "Impossible de lire le dossier :\n{error}",

        # --- menu ---
        "menu_file":            "&Fichier",
        "menu_open_folder":     "&Ouvrir un dossier…",
        "menu_fullscreen":      "Plein écran",
        "menu_quit":            "&Quitter",

        # --- overlay tooltips ---
        "close_tip":            "Fermer la vidéo et revenir à la grille (Échap)",
        "thumb_tip":            "Utiliser l’image actuelle comme miniature de la grille",
        "loop_off_tip":         "Boucle : désactivée  —  cliquer pour activer",
        "loop_on_tip":          "Boucle : activée  —  cliquer pour basculer",
        "loop_tip_fmt":         "Boucle : {state}  —  cliquer pour basculer",
        "loop_on":              "activée",
        "loop_off":             "désactivée",
        "hide_controls_tip":    "Masquer les commandes",
        "show_controls_tip":    "Afficher les commandes",
    },

    "de": {
        # --- dialog chrome ---
        "section_app":          "Video-Raster-Player",
        "section_language":     "Sprache",
        "section_grid":         "Videoraster",
        "section_pages":        "Videoraster-Seiten",
        "section_player":       "Wiedergabe",
        "dialog_title":         "Videos öffnen",
        "app_title":            "Video-Raster-Player",
        "app_desc":             "Wählen Sie einen Ordner mit Ihren Videodateien.\nIhre Videos werden im unten konfigurierten Raster angezeigt.",

        # --- language row ---
        "language_label":       "Sprache:",
        "translate_titles":    "Versuchen, Videotitel in die ausgewählte Sprache zu übersetzen",

        # --- grid size ---
        "rows_label":           "Zeilen:",
        "cols_label":           "Spalten:",

        # --- thumbnail quality ---
        "thumb_quality_label":  "Miniaturbildqualität:",
        "thumb_standard":       "Standard (360p)",
        "thumb_high":           "Hoch (720p)",
        "thumb_ultra":          "Ultra (1080p)",

        # --- checkboxes ---
        "show_titles":          "Videotitel im Raster anzeigen",
        "full_width":           "Vollbreites Layout (keine Abstände zwischen Videos)",
        "use_sidecar":          "Passende Bilddateien als Miniaturbilder verwenden (z. B. video.jpg neben video.mp4)",
        "clip_thumb":           "Seitenverhältnis der Miniaturbilder beibehalten (zuschneiden statt strecken)",
        "show_set_thumb_btn":   "Schaltfläche „Miniaturbild festlegen“ während der Wiedergabe anzeigen",
        "auto_hide":            "Steuerung nach 5 Sekunden automatisch ausblenden",
        "chevron_hides_close":  "Chevron-Schaltfläche blendet auch die Schließen-Schaltfläche (✕) aus",
        "shuffle":              "Zufallswiedergabe — nach dem Ende ein zufälliges Video abspielen",
        "multi_page":           "Mehrere Seiten — alle Videos auf mehreren Rasterseiten anzeigen",
        "page_fill_label":     "Wenn Videos eine Seite nicht gleichmäßig füllen:",
        "page_fill_blank":     "Leere Felder zulassen",
        "page_fill_round_up":  "Anzahl der Seiten aufrunden",
        "page_fill_wrap":      "Leere Felder mit zuvor angezeigten Videos füllen",

        # --- buttons ---
        "choose_folder":        "Ordner auswählen…",
        "open_last":            "Letzten Ordner öffnen",
        "cancel":               "Abbrechen",

        # --- tooltips / messages ---
        "reopen_tip":           "{folder} erneut öffnen",
        "no_last_folder_tip":   "Kein vorheriger Ordner verfügbar — verwenden Sie zuerst „Ordner auswählen…“.",
        "no_videos_title":      "Keine Videos",
        "no_videos_msg":        "In diesem Ordner wurden keine unterstützten Videodateien gefunden.\n\nUnterstützte Erweiterungen: {exts}",
        "folder_error_title":   "Fehler",
        "folder_error_msg":     "Ordner konnte nicht gelesen werden:\n{error}",

        # --- menu ---
        "menu_file":            "&Datei",
        "menu_open_folder":     "Ordner &öffnen…",
        "menu_fullscreen":      "Vollbild",
        "menu_quit":            "&Beenden",

        # --- overlay tooltips ---
        "close_tip":            "Video schließen und zum Raster zurückkehren (Esc)",
        "thumb_tip":            "Aktuelles Bild als Rasterminiatur verwenden",
        "loop_off_tip":         "Schleife: aus  —  klicken zum Aktivieren",
        "loop_on_tip":          "Schleife: ein  —  klicken zum Umschalten",
        "loop_tip_fmt":         "Schleife: {state}  —  klicken zum Umschalten",
        "loop_on":              "ein",
        "loop_off":             "aus",
        "hide_controls_tip":    "Steuerung ausblenden",
        "show_controls_tip":    "Steuerung einblenden",
    },

    "es": {
        # --- dialog chrome ---
        "section_app":          "Reproductor en cuadrícula",
        "section_language":     "Idioma",
        "section_grid":         "Cuadrícula de vídeo",
        "section_pages":        "Páginas de cuadrícula",
        "section_player":       "Reproductor",
        "dialog_title":         "Abrir vídeos",
        "app_title":            "Reproductor en cuadrícula",
        "app_desc":             "Seleccione una carpeta con sus archivos de vídeo.\nSus vídeos se mostrarán en la cuadrícula configurada abajo.",

        # --- language row ---
        "language_label":       "Idioma:",
        "translate_titles":    "Intentar traducir los títulos de vídeo al idioma seleccionado",

        # --- grid size ---
        "rows_label":           "Filas:",
        "cols_label":           "Columnas:",

        # --- thumbnail quality ---
        "thumb_quality_label":  "Calidad de miniaturas:",
        "thumb_standard":       "Estándar (360p)",
        "thumb_high":           "Alta (720p)",
        "thumb_ultra":          "Ultra (1080p)",

        # --- checkboxes ---
        "show_titles":          "Mostrar títulos de vídeo en la cuadrícula",
        "full_width":           "Diseño de ancho completo (sin espacios entre vídeos)",
        "use_sidecar":          "Usar imágenes coincidentes como miniaturas (p. ej. video.jpg junto a video.mp4)",
        "clip_thumb":           "Preservar relación de aspecto de miniaturas (recortar en lugar de estirar)",
        "show_set_thumb_btn":   "Mostrar botón «Establecer miniatura» durante la reproducción",
        "auto_hide":            "Ocultar controles automáticamente después de 5 segundos de reproducción",
        "chevron_hides_close":  "El botón de cheurón también oculta el botón de cerrar (✕)",
        "shuffle":              "Aleatorio — reproducir un vídeo aleatorio al terminar el actual",
        "multi_page":           "Varias páginas — mostrar todos los vídeos en varias páginas de cuadrícula",
        "page_fill_label":     "Cuando los vídeos no llenan una página de manera uniforme:",
        "page_fill_blank":     "Permitir espacios en blanco",
        "page_fill_round_up":  "Redondear hacia arriba el número de páginas",
        "page_fill_wrap":      "Rellenar espacios vacíos con vídeos mostrados anteriormente",

        # --- buttons ---
        "choose_folder":        "Elegir carpeta…",
        "open_last":            "Abrir última carpeta",
        "cancel":               "Cancelar",

        # --- tooltips / messages ---
        "reopen_tip":           "Reabrir {folder}",
        "no_last_folder_tip":   "No hay carpeta anterior disponible — use primero «Elegir carpeta…».",
        "no_videos_title":      "Sin vídeos",
        "no_videos_msg":        "No se encontraron archivos de vídeo compatibles en esa carpeta.\n\nExtensiones admitidas: {exts}",
        "folder_error_title":   "Error",
        "folder_error_msg":     "No se pudo leer la carpeta:\n{error}",

        # --- menu ---
        "menu_file":            "&Archivo",
        "menu_open_folder":     "&Abrir carpeta…",
        "menu_fullscreen":      "Pantalla completa",
        "menu_quit":            "&Salir",

        # --- overlay tooltips ---
        "close_tip":            "Cerrar vídeo y volver a la cuadrícula (Esc)",
        "thumb_tip":            "Usar el fotograma actual como miniatura de la cuadrícula",
        "loop_off_tip":         "Bucle: desactivado  —  clic para activar",
        "loop_on_tip":          "Bucle: activado  —  clic para alternar",
        "loop_tip_fmt":         "Bucle: {state}  —  clic para alternar",
        "loop_on":              "activado",
        "loop_off":             "desactivado",
        "hide_controls_tip":    "Ocultar controles",
        "show_controls_tip":    "Mostrar controles",
    },

    "zh": {
        # --- dialog chrome ---
        "section_app":          "视频网格播放器",
        "section_language":     "语言",
        "section_grid":         "视频网格",
        "section_pages":        "视频网格页面",
        "section_player":       "播放器",
        "dialog_title":         "打开视频",
        "app_title":            "视频网格播放器",
        "app_desc":             "选择包含视频文件的文件夹。\n您的视频将显示在下方配置的网格中。",

        # --- language row ---
        "language_label":       "语言：",
        "translate_titles":    "尝试将视频标题翻译为所选语言",

        # --- grid size ---
        "rows_label":           "行数：",
        "cols_label":           "列数：",

        # --- thumbnail quality ---
        "thumb_quality_label":  "缩略图质量：",
        "thumb_standard":       "标准 (360p)",
        "thumb_high":           "高清 (720p)",
        "thumb_ultra":          "超高清 (1080p)",

        # --- checkboxes ---
        "show_titles":          "在网格中显示视频标题",
        "full_width":           "全宽布局（视频之间无间距）",
        "use_sidecar":          "使用匹配的图片文件作为缩略图（例如 video.mp4 旁边的 video.jpg）",
        "clip_thumb":           "保持缩略图宽高比（裁剪适应而非拉伸）",
        "show_set_thumb_btn":   "播放视频时显示「设置缩略图」按钮",
        "auto_hide":            "播放 5 秒后自动隐藏屏幕控件",
        "chevron_hides_close":  "折叠按钮同时隐藏关闭按钮（✕）",
        "shuffle":              "随机播放 — 当前视频结束后随机播放下一个",
        "multi_page":           "多页显示 — 在多个网格页面中显示所有视频",
        "page_fill_label":     "视频无法均匀填满页面时：",
        "page_fill_blank":     "允许空白格",
        "page_fill_round_up":  "向上取整页数",
        "page_fill_wrap":      "用之前显示的视频填充空白格",

        # --- buttons ---
        "choose_folder":        "选择文件夹…",
        "open_last":            "打开上次文件夹",
        "cancel":               "取消",

        # --- tooltips / messages ---
        "reopen_tip":           "重新打开 {folder}",
        "no_last_folder_tip":   "暂无上次文件夹记录，请先使用「选择文件夹…」。",
        "no_videos_title":      "未找到视频",
        "no_videos_msg":        "该文件夹中未找到受支持的视频文件。\n\n支持的格式：{exts}",
        "folder_error_title":   "错误",
        "folder_error_msg":     "无法读取文件夹：\n{error}",

        # --- menu ---
        "menu_file":            "文件(&F)",
        "menu_open_folder":     "打开文件夹(&O)…",
        "menu_fullscreen":      "全屏",
        "menu_quit":            "退出(&Q)",

        # --- overlay tooltips ---
        "close_tip":            "关闭视频并返回网格（Esc）",
        "thumb_tip":            "将当前帧设为网格缩略图",
        "loop_off_tip":         "循环：关  —  点击启用",
        "loop_on_tip":          "循环：开  —  点击切换",
        "loop_tip_fmt":         "循环：{state}  —  点击切换",
        "loop_on":              "开",
        "loop_off":             "关",
        "hide_controls_tip":    "隐藏控件",
        "show_controls_tip":    "显示控件",
    },

    "ja": {
        # --- dialog chrome ---
        "section_app":          "ビデオグリッドプレイヤー",
        "section_language":     "言語",
        "section_grid":         "ビデオグリッド",
        "section_pages":        "グリッドページ",
        "section_player":       "プレイヤー",
        "dialog_title":         "動画を開く",
        "app_title":            "ビデオグリッドプレイヤー",
        "app_desc":             "動画ファイルの入ったフォルダーを選択してください。\n下の設定に従ってグリッドに表示されます。",

        # --- language row ---
        "language_label":       "言語：",
        "translate_titles":    "動画のタイトルを選択した言語に翻訳する",

        # --- grid size ---
        "rows_label":           "行数：",
        "cols_label":           "列数：",

        # --- thumbnail quality ---
        "thumb_quality_label":  "サムネイル品質：",
        "thumb_standard":       "標準 (360p)",
        "thumb_high":           "高品質 (720p)",
        "thumb_ultra":          "最高 (1080p)",

        # --- checkboxes ---
        "show_titles":          "グリッドにファイル名を表示する",
        "full_width":           "全幅レイアウト（動画間のスペースをなくす）",
        "use_sidecar":          "対応画像ファイルをサムネイルとして使用（例: video.mp4 の隣に video.jpg）",
        "clip_thumb":           "アスペクト比を保持（引き伸ばさずにクリップ）",
        "show_set_thumb_btn":   "再生中に「サムネイルを設定」ボタンを表示する",
        "auto_hide":            "再生開始から5秒後にコントロールを自動非表示",
        "chevron_hides_close":  "シェブロンボタンで閉じるボタン（✕）も非表示にする",
        "shuffle":              "シャッフル — 現在の動画が終わったらランダムに再生",
        "multi_page":           "複数ページ — すべての動画を複数のグリッドページに表示",
        "page_fill_label":     "動画がページに均等に収まらない場合：",
        "page_fill_blank":     "空白セルを許可する",
        "page_fill_round_up":  "ページ数を切り上げる",
        "page_fill_wrap":      "以前に表示した動画で空白を埋める",

        # --- buttons ---
        "choose_folder":        "フォルダーを選択…",
        "open_last":            "最後のフォルダーを開く",
        "cancel":               "キャンセル",

        # --- tooltips / messages ---
        "reopen_tip":           "{folder} を再開く",
        "no_last_folder_tip":   "前回のフォルダーがありません。まず「フォルダーを選択…」を使ってください。",
        "no_videos_title":      "動画なし",
        "no_videos_msg":        "対応する動画ファイルが見つかりませんでした。\n\n対応形式： {exts}",
        "folder_error_title":   "エラー",
        "folder_error_msg":     "フォルダーを読み込めませんでした：\n{error}",

        # --- menu ---
        "menu_file":            "ファイル(&F)",
        "menu_open_folder":     "フォルダーを開く(&O)…",
        "menu_fullscreen":      "フルスクリーン",
        "menu_quit":            "終了(&Q)",

        # --- overlay tooltips ---
        "close_tip":            "動画を閉じてグリッドに戻る（Esc）",
        "thumb_tip":            "現在のフレームをグリッドのサムネイルに設定",
        "loop_off_tip":         "ループ：オフ  —  クリックで有効化",
        "loop_on_tip":          "ループ：オン  —  クリックで切り替え",
        "loop_tip_fmt":         "ループ：{state}  —  クリックで切り替え",
        "loop_on":              "オン",
        "loop_off":             "オフ",
        "hide_controls_tip":    "コントロールを非表示",
        "show_controls_tip":    "コントロールを表示",
    },

    "ko": {
        # --- dialog chrome ---
        "section_app":          "비디오 그리드 플레이어",
        "section_language":     "언어",
        "section_grid":         "비디오 그리드",
        "section_pages":        "그리드 페이지",
        "section_player":       "플레이어",
        "dialog_title":         "동영상 열기",
        "app_title":            "비디오 그리드 플레이어",
        "app_desc":             "동영상 파일이 있는 폴더를 선택하세요.\n아래에서 구성한 그리드에 동영상이 표시됩니다.",

        # --- language row ---
        "language_label":       "언어:",
        "translate_titles":    "동영상 제목을 선택한 언어로 번역 시도",

        # --- grid size ---
        "rows_label":           "행:",
        "cols_label":           "열:",

        # --- thumbnail quality ---
        "thumb_quality_label":  "썸네일 품질:",
        "thumb_standard":       "표준 (360p)",
        "thumb_high":           "고화질 (720p)",
        "thumb_ultra":          "초고화질 (1080p)",

        # --- checkboxes ---
        "show_titles":          "그리드에 동영상 제목 표시",
        "full_width":           "전체 너비 레이아웃 (동영상 사이 간격 없음)",
        "use_sidecar":          "일치하는 이미지 파일을 썸네일로 사용 (예: video.mp4 옆의 video.jpg)",
        "clip_thumb":           "썸네일 종횡비 유지 (늘리지 않고 잘라서 맞춤)",
        "show_set_thumb_btn":   "동영상 재생 중 「썸네일 설정」 버튼 표시",
        "auto_hide":            "재생 5초 후 화면 컨트롤 자동 숨김",
        "chevron_hides_close":  "시브론 버튼이 닫기 버튼(✕)도 함께 숨김",
        "shuffle":              "셔플 — 현재 동영상이 끝나면 무작위 동영상 재생",
        "multi_page":           "여러 페이지 — 모든 동영상을 여러 그리드 페이지에 표시",
        "page_fill_label":     "동영상이 페이지를 균등하게 채우지 못할 때:",
        "page_fill_blank":     "빈 공간 허용",
        "page_fill_round_up":  "페이지 수 올림",
        "page_fill_wrap":      "이전에 표시된 동영상으로 빈 공간 채우기",

        # --- buttons ---
        "choose_folder":        "폴더 선택…",
        "open_last":            "마지막 폴더 열기",
        "cancel":               "취소",

        # --- tooltips / messages ---
        "reopen_tip":           "{folder} 다시 열기",
        "no_last_folder_tip":   "이전 폴더가 없습니다. 먼저 「폴더 선택…」을 사용하세요.",
        "no_videos_title":      "동영상 없음",
        "no_videos_msg":        "해당 폴더에서 지원되는 동영상 파일을 찾을 수 없습니다.\n\n지원 형식: {exts}",
        "folder_error_title":   "오류",
        "folder_error_msg":     "폴더를 읽을 수 없습니다:\n{error}",

        # --- menu ---
        "menu_file":            "파일(&F)",
        "menu_open_folder":     "폴더 열기(&O)…",
        "menu_fullscreen":      "전체 화면",
        "menu_quit":            "종료(&Q)",

        # --- overlay tooltips ---
        "close_tip":            "동영상을 닫고 그리드로 돌아가기 (Esc)",
        "thumb_tip":            "현재 프레임을 그리드 썸네일로 설정",
        "loop_off_tip":         "반복: 꺼짐  —  클릭하여 활성화",
        "loop_on_tip":          "반복: 켜짐  —  클릭하여 전환",
        "loop_tip_fmt":         "반복: {state}  —  클릭하여 전환",
        "loop_on":              "켜짐",
        "loop_off":             "꺼짐",
        "hide_controls_tip":    "컨트롤 숨기기",
        "show_controls_tip":    "컨트롤 표시",
    },
}


def get_strings(language: str) -> dict[str, str]:
    """Return the translation dict for *language*, falling back to English."""
    return TRANSLATIONS.get(language, TRANSLATIONS["en"])
