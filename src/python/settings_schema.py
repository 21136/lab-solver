"""Settings schema version for Electron localStorage migration."""

SETTINGS_SCHEMA_VERSION = 2

SETTINGS_DEFAULTS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "provider": "deepseek",
    "model": "deepseek-chat",
    "codeLanguage": "python",
    "customUrl": "",
    "screenshotChrome": "windows",
    "terminalProfile": "win_powershell",
    "terminalCwd": "",
    "terminalCustom": "",
    "screenshotLayout": "full",
    "includeUml": False,
    "umlAllowOnline": True,
}
