# Contributing

Thanks for taking a look. Bug reports, skins and translations are all welcome.

By contributing you agree that your contribution is licensed under the project's
[PolyForm Noncommercial 1.0.0](LICENSE) licence.

## Getting set up

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Run the headless checks before opening a pull request:

```bat
.venv\Scripts\python tests\test_basics.py
```

They cover settings persistence, skin loading and inheritance, hotkey parsing, source
names and — importantly — that every locale file has exactly the keys `locales/en.json`
has, with matching `{placeholders}`.

## Adding a translation

1. Copy `locales/en.json` to `locales/<code>.json`. Use the plain language code
   (`de`, `pl`) unless the language really needs a region (`pt-BR`, `zh-CN`).
2. Translate the values. Leave the keys alone, and keep every `{placeholder}`
   exactly as it appears in English — the tests check this.
3. Fill in `_meta`: `name` is the language's own name as speakers write it
   (`Deutsch`, not `German`), `code` must match the file name, and add yourself to
   `authors`.
4. Run the tests, then open a pull request.

Keep strings short. The settings window is fairly narrow, and long labels wrap.

You can test a translation without touching the repo at all: drop the file into
`%APPDATA%\Tunetop\locales` and pick the language in the settings — files there
shadow the bundled ones.

## Adding a skin

A skin is a folder with a `skin.json`; see the README for the full schema. Start by
copying `skins/dark` or by writing a short file with `"extends": "dark"` and only the
colours you want to change. Drop it into `%APPDATA%\Tunetop\skins` while you
work on it, then submit it as a folder under `skins/`.

Please make sure a skin stays readable at its declared size, in both normal and compact
mode, and with and without album art.

## Code

- Python 3.10+, standard library plus PySide6 and winsdk. Please don't add dependencies
  without a good reason.
- Every user-facing string goes through `tr()` and gets a key in `locales/en.json`.
  Add the English text; other languages fall back to English until someone translates them.
- Match the surrounding style: type hints on public functions, no comments restating
  what the code plainly does.

## Reporting a bug

Include your Windows version, the player you were controlling, and what the widget
showed versus what you expected. If the app fails to start, run `run-debug.bat` and
paste the console output.
