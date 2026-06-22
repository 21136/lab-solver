"""Settings schema version for Electron localStorage migration."""

SETTINGS_SCHEMA_VERSION = 11

SETTINGS_DEFAULTS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "codeLanguage": "python",
    "customUrl": "",
    "includeUml": False,
    "umlAllowOnline": True,
    # AO-6: standard | deep (react via experimentalReactMode)
    "runMode": "standard",
    "experimentalReactMode": False,
    # AO-3: fast | standard | thorough — controls V4 pipeline depth
    "solveQualityTier": "standard",
    # IR-13a: auto fast tier for theory / code_cloze when tier not user-locked
    "autoFastTierForLightQuestions": True,
    "solveQualityTierExplicit": False,
    # IR-13b: parallel run_code + render_uml (etc.) in orchestrator
    "enableParallelModuleSteps": True,
    # BF50: verify fail → auto remediate once (standard + deep); user can set false
    "autoRemediate": True,
    # IR-8: configurable verify auto-remediate rounds
    "autoRemediateMaxRounds": 1,
    # IR-12: configurable incremental replan rounds
    "maxReplanRounds": 1,
    # IR-16a: persist agent run events to APP_DATA/run_events/{run_id}.jsonl
    "persistRunEvents": True,
    "runEventsMaxFiles": 30,
    "runEventsMaxAgeDays": 7,
    # IR-16b: reject (default) | fifo — queue one pending run when busy
    "runQueueMode": "reject",
    "runQueueMaxDepth": 1,
    # AO-11: v4 default; v1 (LAB_REPORT_USER) deprecated
    "solvePipelineVersion": "v4",
    # IM2-b: local OCR for embedded / scanned assignment images
    "enableImageOcr": False,
    "imageOcrLang": "chi_sim+eng",
    "imageReadingMode": "ocr_only",
    "imageOcrMaxPages": 20,
    "imageVisionMaxPages": 5,
    # AGENT_CAPABILITY_GAPS: C2 behavior learning default on
    "optimizePlanFromUsage": True,
    # AGENT_CAPABILITY_GAPS: optional LLM replan on module failure
    "llmReplan": True,
}
