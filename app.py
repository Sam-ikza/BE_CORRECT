import json
import os
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

import requests
from spellchecker import SpellChecker

GROQ_API_URL ="https://api.groq.com/openai/v1/chat/completions"


@dataclass
class Issue:
    category: str
    message: str
    suggestion: str
    span: Tuple[int, int]


class FastNLPChecker:
    def __init__(self) -> None:
        self.spell = SpellChecker()

    def analyze(self, text: str) -> List[Issue]:
        issues: List[Issue] = []
        issues.extend(self._check_spelling(text))
        issues.extend(self._check_repeated_words(text))
        issues.extend(self._check_sentence_capitalization(text))
        issues.extend(self._check_punctuation(text))
        issues.sort(key=lambda item: item.span[0])
        return issues

    def _check_spelling(self, text: str) -> List[Issue]:
        issues: List[Issue] = []
        word_pattern = re.compile(r"\b[A-Za-z']+\b")
        words = [(m.group(0), m.start(), m.end()) for m in word_pattern.finditer(text)]

        lowered = [w[0].lower() for w in words if len(w[0]) > 1]
        unknown = self.spell.unknown(lowered)

        for word, start, end in words:
            lowered_word = word.lower()
            if len(word) <= 1:
                continue
            if lowered_word in unknown:
                correction = self.spell.correction(lowered_word)
                suggestion = correction if correction else "Check this spelling"
                issues.append(
                    Issue(
                        category="Spelling",
                        message=f"Possible spelling mistake: '{word}'",
                        suggestion=f"Try: {suggestion}",
                        span=(start, end),
                    )
                )
        return issues

    def _check_repeated_words(self, text: str) -> List[Issue]:
        issues: List[Issue] = []
        pattern = re.compile(r"\b(\w+)\s+(\1)\b", re.IGNORECASE)
        for match in pattern.finditer(text):
            word = match.group(1)
            issues.append(
                Issue(
                    category="Grammar",
                    message=f"Repeated word: '{word} {word}'",
                    suggestion=f"Remove one '{word}'",
                    span=(match.start(), match.end()),
                )
            )
        return issues

    def _check_sentence_capitalization(self, text: str) -> List[Issue]:
        issues: List[Issue] = []
        if not text.strip():
            return issues

        start_pattern = re.compile(r"(^|[.!?]\s+)([a-z])")
        for match in start_pattern.finditer(text):
            start = match.start(2)
            end = start + 1
            issues.append(
                Issue(
                    category="Grammar",
                    message="Sentence should start with a capital letter",
                    suggestion=f"Use '{match.group(2).upper()}'",
                    span=(start, end),
                )
            )
        return issues

    def _check_punctuation(self, text: str) -> List[Issue]:
        issues: List[Issue] = []

        for match in re.finditer(r"\s+[,.!?;:]", text):
            issues.append(
                Issue(
                    category="Punctuation",
                    message="Extra space before punctuation",
                    suggestion="Remove the space before punctuation",
                    span=(match.start(), match.end()),
                )
            )

        for match in re.finditer(r" {2,}", text):
            issues.append(
                Issue(
                    category="Punctuation",
                    message="Multiple spaces found",
                    suggestion="Use a single space",
                    span=(match.start(), match.end()),
                )
            )

        for match in re.finditer(r"([!?.,;:])\1+", text):
            punct = match.group(0)
            if punct == "...":
                continue
            issues.append(
                Issue(
                    category="Punctuation",
                    message=f"Repeated punctuation: '{punct}'",
                    suggestion=f"Use a single '{punct[0]}'",
                    span=(match.start(), match.end()),
                )
            )

        stripped = text.rstrip()
        if stripped and stripped[-1] not in ".!?":
            issues.append(
                Issue(
                    category="Punctuation",
                    message="Text appears to be missing ending punctuation",
                    suggestion="Add '.', '!' or '?' at the end",
                    span=(len(stripped) - 1, len(stripped)),
                )
            )

        return issues


def extract_json_block(raw: str) -> Optional[dict]:
    raw = raw.strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    if "```" in raw:
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def get_groq_suggestions(text: str, style: str = "natural") -> Tuple[List[dict], Optional[str]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return [], "GROQ_API_KEY not set. Local checks are still available."

    system_prompt = (
        "You are a writing assistant. Return ONLY valid JSON with this exact schema: "
        "{'suggestions':[{'original':'string','replacement':'string','reason':'string'}]}. "
        "Suggest phrase-level replacements that improve word selection and clarity while preserving meaning. "
        "Keep at most 8 suggestions and avoid unnecessary edits."
    )
    user_prompt = (
        f"Style target: {style}.\n"
        "Analyze this text and suggest improved wording:\n"
        f"{text}"
    )

    payload = {
        "model": "llama-3.1-8b-instant",
        "temperature": 0.2,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Groq request failed: {exc}"

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return [], "Unexpected Groq response format."

    parsed = extract_json_block(content)
    if not parsed or "suggestions" not in parsed or not isinstance(parsed["suggestions"], list):
        return [], "Could not parse AI suggestions as JSON."

    cleaned: List[dict] = []
    for item in parsed["suggestions"][:MAX_AI_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()
        replacement = str(item.get("replacement", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if original and replacement:
            cleaned.append(
                {
                    "original": original,
                    "replacement": replacement,
                    "reason": reason or "Improves clarity.",
                }
            )

    return cleaned, None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Single-File NLP + Groq Writing Assistant")
        self.root.geometry("920x660")
        self.root.minsize(800, 560)

        self.checker = FastNLPChecker()
        self.analyzing = False

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=3)
        self.root.rowconfigure(1, weight=2)

        input_frame = ttk.LabelFrame(self.root, text="Input Text")
        input_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.input_text = tk.Text(input_frame, wrap="word", font=("Segoe UI", 11))
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        input_scroll = ttk.Scrollbar(input_frame, command=self.input_text.yview)
        input_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.input_text.configure(yscrollcommand=input_scroll.set)

        controls = ttk.Frame(self.root)
        controls.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)

        top_controls = ttk.Frame(controls)
        top_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top_controls.columnconfigure(5, weight=1)

        self.style_var = tk.StringVar(value="natural")
        self.ai_enabled_var = tk.BooleanVar(value=True)

        ttk.Label(top_controls, text="AI Style:").grid(row=0, column=0, padx=(0, 6))
        self.style_box = ttk.Combobox(
            top_controls,
            state="readonly",
            textvariable=self.style_var,
            values=["natural", "concise", "formal"],
            width=12,
        )
        self.style_box.grid(row=0, column=1, padx=(0, 12))

        self.ai_check = ttk.Checkbutton(
            top_controls,
            text="Use AI enhancement (Groq)",
            variable=self.ai_enabled_var,
        )
        self.ai_check.grid(row=0, column=2, padx=(0, 12))

        self.analyze_button = ttk.Button(top_controls, text="Analyze", command=self.start_analysis)
        self.analyze_button.grid(row=0, column=3, padx=(0, 8))

        self.clear_button = ttk.Button(top_controls, text="Clear", command=self.clear_all)
        self.clear_button.grid(row=0, column=4, padx=(0, 8))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(top_controls, textvariable=self.status_var, foreground="#2f5d8a").grid(
            row=0, column=5, sticky="e"
        )

        result_frame = ttk.LabelFrame(controls, text="Results")
        result_frame.grid(row=1, column=0, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.result_text = tk.Text(
            result_frame,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            foreground="#222222",
        )
        self.result_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        result_scroll = ttk.Scrollbar(result_frame, command=self.result_text.yview)
        result_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.result_text.configure(yscrollcommand=result_scroll.set)

        self.input_text.insert(
            "1.0",
            "this is teh sample text It has some issues , and maybe repeated repeated words",
        )

    def clear_all(self) -> None:
        if self.analyzing:
            return
        self.input_text.delete("1.0", "end")
        self._set_results("")
        self.status_var.set("Ready")

    def start_analysis(self) -> None:
        if self.analyzing:
            return

        text = self.input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Input required", "Please enter text to analyze.")
            return

        self.analyzing = True
        self.analyze_button.configure(state="disabled")
        self.status_var.set("Analyzing...")

        worker = threading.Thread(target=self._analyze_worker, args=(text,), daemon=True)
        worker.start()

    def _analyze_worker(self, text: str) -> None:
        local_issues = self.checker.analyze(text)

        ai_suggestions: List[dict] = []
        ai_error: Optional[str] = None

        if self.ai_enabled_var.get():
            ai_suggestions, ai_error = get_groq_suggestions(text, self.style_var.get())

        output = self._format_output(local_issues, ai_suggestions, ai_error)
        self.root.after(0, lambda: self._finish_analysis(output, ai_error))

    def _finish_analysis(self, output: str, ai_error: Optional[str]) -> None:
        self._set_results(output)
        if ai_error:
            self.status_var.set("Done (local + AI fallback)")
        else:
            self.status_var.set("Done")
        self.analyzing = False
        self.analyze_button.configure(state="normal")

    def _set_results(self, content: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", content)
        self.result_text.configure(state="disabled")

    def _format_output(
        self,
        local_issues: List[Issue],
        ai_suggestions: List[dict],
        ai_error: Optional[str],
    ) -> str:
        lines: List[str] = []

        lines.append("=== Local Fast Checks ===")
        if not local_issues:
            lines.append("No local issues detected.")
        else:
            for idx, issue in enumerate(local_issues, start=1):
                lines.append(
                    f"{idx}. [{issue.category}] {issue.message} | Suggestion: {issue.suggestion} | Span: {issue.span}"
                )

        lines.append("")
        lines.append("=== AI Enhanced Suggestions (Groq) ===")
        if ai_error:
            lines.append(f"AI unavailable: {ai_error}")
        elif not ai_suggestions:
            lines.append("No AI suggestions returned.")
        else:
            for idx, item in enumerate(ai_suggestions, start=1):
                lines.append(
                    f"{idx}. Replace '{item['original']}' -> '{item['replacement']}' | Why: {item['reason']}"
                )

        return "\n".join(lines)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
