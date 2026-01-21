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
        "projectPath": "E:/HarmonyOS/project/HarmoneyOpenEye/entry",
        "projectMainPagePath": "E:/HarmonyOS/project/HarmoneyOpenEye/entry/src/main/resources/base/profile/main_pages.json",
    },
    "HarmonyMovieMusic": {
        "projectName": "Harmony-arkts-movie-music-app-ui",
        "projectPath": "E:/HarmonyOS/project/Harmony-arkts-movie-music-app-ui/entry",
        "projectMainPagePath": "E:/HarmonyOS/project/Harmony-arkts-movie-music-app-ui/entry/src/main/resources/base/profile/main_pages.json",
    },
    "ArkTSWPHUI": {
        "projectName": "ArkTS-wphui1.0",
        "projectPath": "E:/HarmonyOS/project/ArkTS-wphui1.0/entry",
        "projectMainPagePath": "E:/HarmonyOS/project/ArkTS-wphui1.0/entry/src/main/resources/base/profile/main_pages.json",
    },
    "MultiDeviceMusic": {
        "projectName": "MultiDeviceMusic",
        "projectPath": "E:/HarmonyOS/project/codelabs/MultiDeviceMusic/entry",
        "projectMainPagePath": "E:/HarmonyOS/project/codelabs/MultiDeviceMusic/entry/src/main/resources/base/profile/main_pages.json",
    },
    "Biandan": {
        "projectName": "Biandan",
        "projectPath": "E:/HarmonyOS/project/biandan-satge/entry",
        "projectMainPagePath": "E:/HarmonyOS/project/biandan-satge/entry/src/main/resources/base/profile/main_pages.json",
    },
    "MultiShopping": {
        "projectName": "MultiShopping",
        "projectPath": "E:/HarmonyOS/project/codelabs/MultiShopping/product/phone",
        "projectMainPagePath": "E:/HarmonyOS/project/codelabs/MultiShopping/product/phone/src/main/resources/base/profile/main_pages.json",
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