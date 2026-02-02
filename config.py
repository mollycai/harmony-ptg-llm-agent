LLM_CONFIG = {
    "deepseek": {
        "baseURL": "https://api.deepseek.com",
        "apiKeyEnv": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "preprocessModel": "deepseek-chat",
    },
    "glm": {
        "baseURL": "https://open.bigmodel.cn/api/paas/v4/",
        "apiKeyEnv": "GLM_API_KEY",
        "model": "glm-4.7",
        "preprocessModel": "glm-4.7",
    },
    "doubao": {
        "baseURL": "https://ark.cn-beijing.volces.com/api/v3",
        "apiKeyEnv": "DOUBAO_API_KEY",
        "model": "doubao-seed-1-8-251215",
        "preprocessModel": "doubao-seed-1-8-251215",
    },
}

PROJECT_CONFIG = {
    "HarmoneyOpenEye": {
        "projectName": "HarmoneyOpenEye",
        "projectPath": "/Users/edwincai/MUST/projects/HarmoneyOpenEye/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/HarmoneyOpenEye/entry/src/main/resources/base/profile/main_pages.json",
    },
    "HarmonyMovieMusic": {
        "projectName": "Harmony-arkts-movie-music-app-ui",
        "projectPath": "/Users/edwincai/MUST/projects/Harmony-arkts-movie-music-app-ui/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/Harmony-arkts-movie-music-app-ui/entry/src/main/resources/base/profile/main_pages.json",
    },
    "ArkTSWPHUI": {
        "projectName": "ArkTS-wphui1.0",
        "projectPath": "/Users/edwincai/MUST/projects/ArkTS-wphui1.0/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/ArkTS-wphui1.0/entry/src/main/resources/base/profile/main_pages.json",
    },
    "MultiDeviceMusic": {
        "projectName": "MultiDeviceMusic",
        "projectPath": "/Users/edwincai/MUST/projects/codelabs/MultiDeviceMusic/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/codelabs/MultiDeviceMusic/entry/src/main/resources/base/profile/main_pages.json",
    },
    "Biandan": {
        "projectName": "Biandan",
        "projectPath": "/Users/edwincai/MUST/projects/biandan-satge/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/biandan-satge/entry/src/main/resources/base/profile/main_pages.json",
    },
    "MultiShopping": {
        "projectName": "MultiShopping",
        "projectPath": "/Users/edwincai/MUST/projects/codelabs/MultiShopping/product/phone",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/codelabs/MultiShopping/product/phone/src/main/resources/base/profile/main_pages.json",
    },
}


def get_llm_config(provider: str) -> dict:
    key = (provider or "deepseek").strip().lower()
    if key not in LLM_CONFIG:
        raise ValueError(f'Unknown provider "{provider}". Supported: {", ".join(LLM_CONFIG.keys())}')
    return LLM_CONFIG[key]


def get_project_config(project: str) -> dict:
    key = (project or "HarmoneyOpenEye").strip()
    if key not in PROJECT_CONFIG:
        raise ValueError(f'Unknown project "{project}". Supported: {", ".join(PROJECT_CONFIG.keys())}')
    return PROJECT_CONFIG[key]