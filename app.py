import ast
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

GROQ_API_URL =  "https://api.groq.com/openai/v1/chat/completions"
MAX_AI_SUGGESTIONS = 8


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


def extract_json_block(raw: str) -> Optional[object]:
    raw = raw.strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            pass

    if "```" in raw:
        raw = re.sub(r"```[a-zA-Z]*", "", raw).replace("```", "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                pass

    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                pass

    return None


def normalize_suggestions(parsed: object) -> List[dict]:
    if isinstance(parsed, dict):
        items = parsed.get("suggestions", [])
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = []

    cleaned: List[dict] = []
    for item in items[:MAX_AI_SUGGESTIONS]:
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
    return cleaned


def extract_text_suggestions(raw: str) -> List[dict]:
    suggestions: List[dict] = []
    for line in raw.splitlines():
        line = line.strip(" -\t")
        line = re.sub(r"^\d+[.)]\s*", "", line)
        original = ""
        replacement = ""

        arrow_match = re.search(r"(.+?)\s*(?:->|=>|→)\s*(.+)", line)
        replace_match = re.search(
            r"replace\s+[\"']?(.+?)[\"']?\s+with\s+[\"']?(.+?)[\"']?$",
            line,
            re.IGNORECASE,
        )

        if arrow_match:
            original = arrow_match.group(1).strip(" ' \t:0123456789.")
            replacement = arrow_match.group(2).strip(" ' \t")
        elif replace_match:
            original = replace_match.group(1).strip()
            replacement = replace_match.group(2).strip()

        if original and replacement:
            suggestions.append(
                {
                    "original": original,
                    "replacement": replacement,
                    "reason": "Improves clarity.",
                }
            )
    return suggestions[:MAX_AI_SUGGESTIONS]


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
    normalized = normalize_suggestions(parsed)
    if not normalized:
        fallback = extract_text_suggestions(content)
        if fallback:
            return fallback, None
        return [], "Could not parse AI suggestions as JSON."

    return normalized, None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Single-File NLP + Groq Writing Assistant")
        self.root.geometry("980x700")
        self.root.minsize(800, 560)

        self.checker = FastNLPChecker()
        self.analyzing = False
        self.char_count_var = tk.StringVar(value="0 chars | 0 words")
        self.tone_options = {
            "Natural (balanced)": "natural",
            "Concise (short + clear)": "concise",
            "Formal (professional)": "formal",
        }
        self.tone_hint_map = {
            "natural": "Balanced tone for everyday writing.",
            "concise": "Shorter phrasing with less fluff.",
            "formal": "Professional and polished wording.",
        }

        self._configure_theme()
        self.root.bind("<Control-Return>", self._trigger_analyze)
        self.root.bind("<Control-l>", self._trigger_clear)

        self._build_ui()

    def _configure_theme(self) -> None:
        self.root.configure(bg="#10131a")
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background="#10131a", foreground="#e5e7eb")
        style.configure("TFrame", background="#10131a")
        style.configure("TLabelframe", background="#10131a", bordercolor="#2a3341")
        style.configure("TLabelframe.Label", background="#10131a", foreground="#e5e7eb")
        style.configure("TLabel", background="#10131a", foreground="#cbd5e1")
        style.configure(
            "Title.TLabel",
            background="#10131a",
            foreground="#f8fafc",
            font=("Segoe UI Semibold", 14),
        )
        style.configure(
            "Subtle.TLabel",
            background="#10131a",
            foreground="#94a3b8",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Tone.TLabel",
            background="#10131a",
            foreground="#ff9f1c",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "ToneHint.TLabel",
            background="#10131a",
            foreground="#ffbf69",
            font=("Segoe UI", 9),
        )
        style.configure(
            "TButton",
            background="#1f2937",
            foreground="#f8fafc",
            borderwidth=0,
            focusthickness=3,
            focuscolor="#334155",
            padding=(12, 7),
        )
        style.map(
            "TButton",
            background=[("active", "#334155"), ("disabled", "#1f2937")],
            foreground=[("disabled", "#64748b")],
        )
        style.configure("Accent.TButton", background="#0ea5e9", foreground="#0f172a")
        style.map("Accent.TButton", background=[("active", "#38bdf8")])
        style.configure("TCheckbutton", background="#10131a", foreground="#cbd5e1")
        style.map("TCheckbutton", background=[("active", "#10131a")])
        style.configure(
            "TCombobox",
            fieldbackground="#0f172a",
            background="#1f2937",
            foreground="#e5e7eb",
            arrowcolor="#cbd5e1",
        )
        style.configure(
            "Tone.TCombobox",
            fieldbackground="#261708",
            background="#2f1c09",
            foreground="#ffd9a6",
            arrowcolor="#ff9f1c",
        )

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        ttk.Label(header, text="BE_CORRECT", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Fast local checks + optional Groq AI suggestions",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=3)
        self.root.rowconfigure(2, weight=2)

        input_frame = ttk.LabelFrame(self.root, text="Input Text")
        input_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(2, 8))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.input_text = tk.Text(
            input_frame,
            wrap="word",
            font=("Segoe UI", 11),
            bg="#0b1220",
            fg="#e2e8f0",
            insertbackground="#f8fafc",
            selectbackground="#1d4ed8",
            relief="flat",
            padx=12,
            pady=10,
        )
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)

        input_scroll = ttk.Scrollbar(input_frame, command=self.input_text.yview)
        input_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.input_text.configure(yscrollcommand=input_scroll.set)
        self.input_text.bind("<KeyRelease>", self._update_text_metrics)

        controls = ttk.Frame(self.root)
        controls.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)

        top_controls = ttk.Frame(controls)
        top_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top_controls.columnconfigure(6, weight=1)

        self.style_var = tk.StringVar(value="Natural (balanced)")
        self.tone_hint_var = tk.StringVar(value=self.tone_hint_map["natural"])
        self.ai_enabled_var = tk.BooleanVar(value=True)

        ttk.Label(top_controls, text="Tone:", style="Tone.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.style_box = ttk.Combobox(
            top_controls,
            state="readonly",
            textvariable=self.style_var,
            values=list(self.tone_options.keys()),
            width=22,
            style="Tone.TCombobox",
        )
        self.style_box.grid(row=0, column=1, padx=(0, 12))
        self.style_box.bind("<<ComboboxSelected>>", self._on_tone_change)

        self.ai_check = ttk.Checkbutton(
            top_controls,
            text="Use AI enhancement (Groq)",
            variable=self.ai_enabled_var,
        )
        self.ai_check.grid(row=0, column=2, padx=(0, 12))

        self.analyze_button = ttk.Button(
            top_controls, text="Analyze", command=self.start_analysis, style="Accent.TButton"
        )
        self.analyze_button.grid(row=0, column=3, padx=(0, 8))

        self.clear_button = ttk.Button(top_controls, text="Clear", command=self.clear_all)
        self.clear_button.grid(row=0, column=4, padx=(0, 8))

        ttk.Label(top_controls, textvariable=self.char_count_var, style="Subtle.TLabel").grid(
            row=0, column=5, sticky="w", padx=(2, 10)
        )

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(top_controls, textvariable=self.status_var, style="Subtle.TLabel").grid(row=0, column=6, sticky="e")
        ttk.Label(top_controls, textvariable=self.tone_hint_var, style="ToneHint.TLabel").grid(
            row=1, column=0, columnspan=7, sticky="w", pady=(6, 0)
        )
        tk.Frame(top_controls, bg="#ff8a00", height=2).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0)
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
            bg="#0b1220",
            fg="#e2e8f0",
            insertbackground="#f8fafc",
            selectbackground="#1d4ed8",
            relief="flat",
            padx=12,
            pady=10,
        )
        self.result_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)

        result_scroll = ttk.Scrollbar(result_frame, command=self.result_text.yview)
        result_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.result_text.configure(yscrollcommand=result_scroll.set)

        self.input_text.insert(
            "1.0",
            "this is teh sample text It has some issues , and maybe repeated repeated words",
        )
        self._update_text_metrics()

    def _trigger_analyze(self, _event: object = None) -> str:
        self.start_analysis()
        return "break"

    def _trigger_clear(self, _event: object = None) -> str:
        self.clear_all()
        return "break"

    def _update_text_metrics(self, _event: object = None) -> None:
        text = self.input_text.get("1.0", "end-1c")
        chars = len(text)
        words = len([w for w in text.split() if w.strip()])
        self.char_count_var.set(f"{chars} chars | {words} words")

    def _on_tone_change(self, _event: object = None) -> None:
        self.tone_hint_var.set(self.tone_hint_map.get(self._selected_style_key(), ""))

    def _selected_style_key(self) -> str:
        return self.tone_options.get(self.style_var.get(), "natural")

    def clear_all(self) -> None:
        if self.analyzing:
            return
        self.input_text.delete("1.0", "end")
        self._set_results("")
        self.status_var.set("Ready")
        self._update_text_metrics()

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
            ai_suggestions, ai_error = get_groq_suggestions(text, self._selected_style_key())

        output = self._format_output(text, local_issues, ai_suggestions, ai_error)
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
        source_text: str,
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

        lines.append("")
        lines.append("=== Final Corrected Text (Block 4) ===")
        corrected = self._build_corrected_text(source_text, ai_suggestions)
        lines.append(corrected)

        return "\n".join(lines)

    def _build_corrected_text(self, text: str, ai_suggestions: List[dict]) -> str:
        corrected = text
        for item in ai_suggestions:
            original = str(item.get("original", "")).strip()
            replacement = str(item.get("replacement", "")).strip()
            if not original or not replacement:
                continue
            if original in corrected:
                corrected = corrected.replace(original, replacement, 1)
        return corrected


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
