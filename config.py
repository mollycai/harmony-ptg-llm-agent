LLM_CONFIG = {
    "deepseek": {
        "baseURL": "https://api.deepseek.com",
        "apiKeyEnv": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "preprocessModel": "deepseek-chat",
        "chatOptions": {
            "temperature": 0,
            "top_p": 1,
            "timeout": 180,
            "max_retries": 2,
        },
    },
    "gpt": {
        "baseURL": "https://api.gptsapi.net/v1",
        "apiKeyEnv": "OPENAI_API_KEY",
        "model": "gpt-5.4",
        "preprocessModel": "gpt-5.4",
        "chatOptions": {
            "temperature": 0,
            "top_p": 1,
            "timeout": 180,
            "max_retries": 2,
        },
    },
    "claude": {
        "baseURL": "https://api.gptsapi.net/v1",
        "apiKeyEnv": "CLAUDE_API_KEY",
        "model": "wild-opus-4-6",
        "preprocessModel": "wild-opus-4-6",
        "chatOptions": {
            "temperature": 0,
            "top_p": 1,
            "timeout": 180,
            "max_retries": 2,
        },
    },
}

PROJECT_CONFIG = {
    "HarmoneyOpenEye": {
        "projectName": "HarmoneyOpenEye",
        "projectPath": "/Users/edwincai/MUST/projects/HarmoneyOpenEye/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/HarmoneyOpenEye/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "HarmonyMovieMusic": {
        "projectName": "Harmony-arkts-movie-music-app-ui",
        "projectPath": "/Users/edwincai/MUST/projects/Harmony-arkts-movie-music-app-ui/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/Harmony-arkts-movie-music-app-ui/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "ArkTSWPHUI": {
        "projectName": "ArkTS-wphui1.0",
        "projectPath": "/Users/edwincai/MUST/projects/ArkTS-wphui1.0/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/ArkTS-wphui1.0/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "MultiDeviceMusic": {
        "projectName": "MultiDeviceMusic",
        "projectPath": "/Users/edwincai/MUST/projects/codelabs/MultiDeviceMusic/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/codelabs/MultiDeviceMusic/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "Biandan": {
        "projectName": "Biandan",
        "projectPath": "/Users/edwincai/MUST/projects/biandan-satge/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/biandan-satge/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "OpenNeteasy": {
        "projectName": "open-neteasy",
        "projectPath": "/Users/edwincai/MUST/projects/open-neteasy/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/open-neteasy/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "MseaHarmonyOS": {
        "projectName": "Msea-HarmonyOS",
        "projectPath": "/Users/edwincai/MUST/projects/Msea-HarmonyOS/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/Msea-HarmonyOS/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "HomeworkTaskist": {
        "projectName": "homework-taskist",
        "projectPath": "/Users/edwincai/MUST/projects/homework-taskist/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/homework-taskist/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "OnBill": {
        "projectName": "on-bill",
        "projectPath": "/Users/edwincai/MUST/projects/on-bill/entry",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/on-bill/entry/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
        },
    },
    "MultiShopping": {
        "projectName": "MultiShopping",
        "projectPath": "/Users/edwincai/MUST/projects/codelabs/MultiShopping/product/phone",
        "projectMainPagePath": "/Users/edwincai/MUST/projects/codelabs/MultiShopping/product/phone/src/main/resources/base/profile/main_pages.json",
        "importAliasMap": {
            "@/": "src/main/ets",
            "@entry/": "src/main/ets",
            "@common/": "../common/src/main/ets",
        },
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
