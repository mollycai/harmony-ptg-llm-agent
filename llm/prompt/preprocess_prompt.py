PREPROCESS_PROMPT_TEMPLATE = """
### Role
You are an expert HarmonyOS ArkTS developer.

### Goal
Given one ArkTS/ETS source file, output a compact code skeleton that preserves everything needed to recover navigation/routing relationships and to trace how a main page instantiates nested components.

### Keep (must)
1. All navigation/routing API calls and their arguments/targets, including but not limited to:
   - router.pushUrl, router.replaceUrl, router.back, router.clear, router.push, router.replace
   - Router.push, Router.replace, pushUrl, replaceUrl, back
   - Navigator.push, Navigator.pop
   - Navigation.pushPath, Navigation.pop, NavPathStack.pushPath, NavPathStack.pop
   - Any custom wrapper functions that call the above.
2. All imports/exports that reference:
   - pages, routes, navigation helpers/wrappers, constants/enums used as navigation targets.
   - custom UI components instantiated in build trees.
3. All event handlers and the minimal parent component chain that contains them (e.g., Column > List > ForEach > ListItem > ...).
4. String literals, route-path constants/enums/objects related to navigation (do not replace or rename them).

### Prune (aggressively)
- Styling, layout properties, resource ids, state variables, non-navigation business logic.
- Non-essential UI siblings that do not contain navigation and do not help connect to nested components.

### Special rule: wiring for cross-file analysis
If the file has no direct navigation calls, still keep:
- @Entry/@Component declarations
- build() tree structure
- custom component instantiations (e.g., HomePage(), MyItemComponent({...})) and their props/event handlers
This is needed so a later pass can follow imports/instantiation chains.

### Input
<source_code>
{{CODE}}
</source_code>

### Output
Return ONLY the simplified ArkTS code skeleton. Do not add explanations.
""".strip()


def get_preprocess_prompt(code: str) -> str:
    return PREPROCESS_PROMPT_TEMPLATE.replace("{{CODE}}", code or "")