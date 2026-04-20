# Single-File NLP + Groq Writing Assistant

This project is a single-file Python app that checks text for:
- Spelling mistakes
- Basic grammar issues
- Basic punctuation issues
- Optional AI-enhanced wording suggestions using Groq

Everything is in one file: app.py

## What This App Does

The app has two layers:
1. Fast local checks (always available)
- Uses pyspellchecker and regex rules.
- Runs offline and returns quickly.

2. AI enhancement (optional)
- Uses Groq API for better word-choice suggestions.
- If GROQ_API_KEY is missing or request fails, app still works in local mode.

## Project Structure

- app.py: Complete GUI + local NLP logic + Groq API logic.
- README.md: Setup and usage guide.

## Requirements

- Python 3.10+ (works with newer versions too)
- pip

Python packages:
- requests
- pyspellchecker

Install:

```powershell
python -m pip install requests pyspellchecker
```

## Important Groq Configuration

In app.py, this constant must be the Groq endpoint URL:

```python
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
```

If this value contains your API key instead of URL, AI mode will fail.

Security note:
- Never hardcode your Groq key inside source code.
- Store it in environment variable GROQ_API_KEY.

## How To Run

From project folder (X:\gen-ai-prj):

```powershell
python .\app.py
```

If python command is not mapped:

```powershell
x:/gen-ai-prj/.venv/Scripts/python.exe x:/gen-ai-prj/app.py
```

## Run With Groq Enabled

Set key for current terminal session:

```powershell
$env:GROQ_API_KEY="your_groq_api_key"
```

Then run:

```powershell
python .\app.py
```

In UI:
- Keep "Use AI enhancement (Groq)" checked.
- Choose style: natural / concise / formal.
- Click Analyze.

## How It Works Internally

Main flow:
1. User enters text in Tkinter input box.
2. Clicking Analyze starts a background thread.
3. Local checks run first via FastNLPChecker:
- _check_spelling
- _check_repeated_words
- _check_sentence_capitalization
- _check_punctuation
4. If AI checkbox is enabled, get_groq_suggestions is called.
5. AI response is parsed as JSON via extract_json_block.
6. UI shows two result sections:
- Local Fast Checks
- AI Enhanced Suggestions (Groq)

## Local Checks Included

Spelling:
- Unknown words from pyspellchecker dictionary

Grammar:
- Repeated words (example: "the the")
- Sentence-start lowercase letter

Punctuation:
- Extra space before punctuation
- Multiple spaces
- Repeated punctuation (except ...)
- Missing terminal punctuation

## Troubleshooting

1. AI unavailable: GROQ_API_KEY not set
- Set environment variable and rerun.

2. Groq request failed
- Check internet access.
- Confirm key is valid.
- Confirm GROQ_API_URL is correct endpoint.

3. No AI suggestions returned
- Input may already be clear.
- Try longer text with awkward phrasing.

4. App does not start
- Install dependencies again.
- Verify Python path and run command.

## Quick Test Input

Try this text:

this is teh sample text It has some issues , and maybe repeated repeated words

Expected:
- Spelling issue for "teh"
- Grammar issue for repeated word
- Punctuation issue for space before comma
- Possible capitalization warning
