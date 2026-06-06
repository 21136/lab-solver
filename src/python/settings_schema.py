"""Settings schema version for Electron localStorage migration."""

SETTINGS_SCHEMA_VERSION = 5

SETTINGS_DEFAULTS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "provider": "deepseek",
    "model": "deepseek-chat",
    "codeLanguage": "python",
    "customUrl": "",
    "includeUml": False,
    "umlAllowOnline": True,
    # AO-6: standard | deep (react via experimentalReactMode)
    "runMode": "standard",
    "experimentalReactMode": False,
    # AO-3: fast | standard | thorough — controls V4 pipeline depth
    "solveQualityTier": "standard",
    # AO-11: v4 default; v1 (LAB_REPORT_USER) deprecated
    "solvePipelineVersion": "v4",
    # IM2-b: local OCR for embedded / scanned assignment images
    "enableImageOcr": False,
    "imageOcrLang": "chi_sim+eng",
    "imageReadingMode": "ocr_only",
    "imageOcrMaxPages": 20,
    "imageVisionMaxPages": 5,
}
