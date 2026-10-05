"""Draft an email from a screenshot.

The screenshot is the only source of facts. Recipient, address, dates, and
amounts are copied from the image. Anything that is not visible is left blank.

Usage:
  python draft_email.py --serve      # paste with Ctrl+V in the browser
  python draft_email.py shot.png
  python draft_email.py              # image currently on the clipboard

Requires OPENAI_API_KEY. Optional:
  OPENAI_BASE_URL     default https://api.openai.com/v1
  EMAIL_DRAFT_MODEL   default gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SYSTEM_PROMPT = """You write the user's reply to the person who sent the message in the screenshots.

The screenshots show an email or chat someone sent to the user. Write a new message back to that sender, answering what they wrote. Read every screenshot, in order. Together they are one thread.

Who the reply is to:
- to_name and to_email are the sender of the message in the screenshots. That is the person the user is replying to.
- On an email, the sender is the From line. The To line is the user, so do not address the reply to the user.
- The name in the greeting, such as "Hey Mohit", is the user. Sign the reply with that name when it is visible.
- Copy to_email only when the sender's address is visible. Otherwise leave it empty.

What to write:
- body is the user's reply to that sender. Respond to their request or question.
- Do not rewrite, polish, shorten, or reproduce their message as the draft.
- Do not write as if you are the sender in the screenshot.
- subject is the reply subject. When their subject is visible, use "Re: " and that subject.
- The user's note says how to reply. Follow it. Do not paste the note into the email unless they ask you to include those words.
- Use every screenshot. Reply to the latest message, and use the earlier screenshots as context.
- Use only facts that appear in the screenshots or the note.
- Write in the same language as the message being answered.
- Keep the tone direct and professional.
- Never invent an email address, phone number, date, price, or commitment.

Return one JSON object with these keys:
- to_name: sender's name, or "" if it is not visible
- to_email: sender's address, or "" if it is not visible
- subject: the reply subject
- body: the reply, with a greeting and a sign-off
- notes: one sentence on anything you could not see and therefore left out
"""


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")


def image_from_clipboard(destination: Path) -> None:
    """Save the current Windows clipboard image to destination."""
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$image = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $image) {{ exit 2 }}
$image.Save('{destination}')
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not destination.exists():
        raise SystemExit(
            "No image on the clipboard. Copy a screenshot, or pass a file path."
        )


def build_request(
    images: list[tuple[bytes, str]],
    note: str | None = None,
    tone: str | None = None,
) -> dict:
    if not images:
        raise DraftError("Paste a screenshot first.")
    instruction = (note or "").strip() or "Reply to what they asked."
    if tone:
        instruction += f" Tone: {tone}."
    count = len(images)
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"There are {count} screenshots. Use every one. "
                "Write the user's reply to the sender. Do not rewrite the sender's message.\n"
                f"How to reply: {instruction}"
            ),
        }
    ]
    for index, (image_bytes, media_type) in enumerate(images, start=1):
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append({"type": "text", "text": f"Screenshot {index} of {count}."})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{encoded}"},
            }
        )
    model = os.environ.get("EMAIL_DRAFT_MODEL", "gpt-4.1-mini")
    return {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }


class DraftError(Exception):
    """A draft could not be produced from the screenshot."""


def call_vision(payload: dict) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise DraftError("Set OPENAI_API_KEY, then run this again.")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise DraftError(f"Vision API returned {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise DraftError(f"Could not reach the vision API: {error.reason}") from error
    content = raw["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise DraftError("The model did not return a draft.") from error


def decode_image(media_type: str, data: str) -> tuple[bytes, str]:
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if media_type not in allowed:
        raise DraftError("Paste a PNG, JPEG, WEBP, or GIF screenshot.")
    if data.startswith("data:"):
        _, _, data = data.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError as error:
        raise DraftError("Could not read that image.") from error
    if not raw:
        raise DraftError("That image was empty.")
    if len(raw) > 12 * 1024 * 1024:
        raise DraftError("That screenshot is larger than 12 MB.")
    return raw, media_type


def images_from_payload(incoming: dict) -> list[tuple[bytes, str]]:
    raw_images = incoming.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise DraftError("Paste a screenshot first.")
    if len(raw_images) > 8:
        raise DraftError("Paste up to 8 screenshots.")
    decoded = []
    for item in raw_images:
        if not isinstance(item, dict):
            raise DraftError("Could not read that image.")
        decoded.append(
            decode_image(
                str(item.get("media_type") or ""),
                str(item.get("data") or ""),
            )
        )
    return decoded


def note_from_payload(incoming: dict) -> str:
    note = incoming.get("note")
    if note is None:
        return ""
    if not isinstance(note, str):
        raise DraftError("The note has to be text.")
    if len(note) > 2000:
        raise DraftError("Keep the note under 2000 characters.")
    return note


def render(draft: dict) -> str:
    to_name = (draft.get("to_name") or "").strip()
    to_email = (draft.get("to_email") or "").strip()
    if to_name and to_email:
        to_line = f"{to_name} <{to_email}>"
    else:
        to_line = to_name or to_email or "(not in the screenshot)"
    parts = [
        f"To: {to_line}",
        f"Subject: {(draft.get('subject') or '').strip()}",
        "",
        (draft.get("body") or "").strip(),
    ]
    notes = (draft.get("notes") or "").strip()
    if notes:
        parts.extend(["", f"Notes: {notes}"])
    return "\n".join(parts).rstrip() + "\n"


def load_image(path: str | None) -> tuple[bytes, str]:
    if path:
        image_path = Path(path)
        if not image_path.is_file():
            raise SystemExit(f"File not found: {image_path}")
        return image_path.read_bytes(), media_type_for(image_path)

    with tempfile.TemporaryDirectory() as directory:
        clip_path = Path(directory) / "clipboard.png"
        image_from_clipboard(clip_path)
        return clip_path.read_bytes(), "image/png"


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Draft</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3efe6;
      --ink: #1d1a16;
      --muted: #6e675e;
      --line: #ddd4c6;
      --card: #fffdf8;
      --accent: #1f4d3a;
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", sans-serif;
    }
    main {
      width: min(760px, calc(100% - 32px));
      margin: 0 auto;
      padding: 48px 0 72px;
    }
    h1 {
      margin: 0 0 8px;
      font-family: Georgia, "Iowan Old Style", serif;
      font-size: 2.1rem;
      font-weight: 500;
    }
    .lede { margin: 0 0 28px; color: var(--muted); }
    .hint {
      display: grid;
      place-items: center;
      min-height: 320px;
      padding: 32px;
      text-align: center;
      background: rgba(255, 253, 248, 0.7);
      border: 1.5px dashed #c9bfb0;
      border-radius: 18px;
    }
    .hint strong { display: block; margin-bottom: 8px; font-size: 1.25rem; }
    kbd {
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-bottom-width: 2px;
      border-radius: 6px;
      background: white;
      font-family: inherit;
    }
    .again { margin: 14px 0 0; color: var(--muted); }
    .composer {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 18px;
    }
    .composer label { margin-top: 0; }
    .shots {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 12px;
    }
    .thumb {
      position: relative;
      margin: 0;
    }
    .thumb img {
      display: block;
      width: 100%;
      height: 180px;
      object-fit: contain;
      background: white;
      border: 1px solid var(--line);
      border-radius: 14px;
    }
    button.primary {
      margin-top: 16px;
      padding: 10px 18px;
      color: white;
      font: inherit;
      background: var(--accent);
      border: 0;
      border-radius: 999px;
      cursor: pointer;
    }
    .composer button.primary { margin-top: 0; }
    button.primary:disabled { opacity: 0.45; cursor: default; }
    button.remove {
      position: absolute;
      top: 8px;
      right: 8px;
      margin: 0;
      padding: 4px 8px;
      color: var(--ink);
      font: inherit;
      font-size: 0.78rem;
      background: white;
      border: 1px solid var(--line);
      border-radius: 999px;
      cursor: pointer;
    }
    @media (max-width: 640px) {
      .composer { grid-template-columns: 1fr; }
    }
    .status { min-height: 1.5em; margin: 14px 0; color: var(--muted); }
    .status.error { color: #8a2f24; }
    .email {
      padding: 8px 18px 18px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
    }
    label { display: block; margin-top: 14px; color: var(--muted); font-size: 0.82rem; }
    input, textarea {
      width: 100%;
      margin-top: 6px;
      padding: 10px 12px;
      color: inherit;
      font: inherit;
      background: white;
      border: 1px solid var(--line);
      border-radius: 10px;
    }
    textarea { min-height: 240px; line-height: 1.5; resize: vertical; }
    .notes { margin: 12px 0 0; color: var(--muted); font-size: 0.92rem; }
    button.primary:focus-visible, button.remove:focus-visible, input:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
  </style>
</head>
<body>
  <main>
    <h1>Draft</h1>
    <p class="lede">Paste each screenshot with Ctrl+V. Every paste is added. Then press Write email.</p>
    <form class="composer" id="composer">
      <label>Note
        <input id="note" name="note" value="What to reply to this" autocomplete="off">
      </label>
      <button class="primary" type="submit" id="write" disabled>Write email</button>
    </form>
    <section class="hint" id="empty">
      <div>
        <strong>Paste screenshots</strong>
        <span><kbd>Ctrl</kbd> + <kbd>V</kbd></span>
      </div>
    </section>
    <div class="shots" id="shots" hidden></div>
    <p class="again" id="again" hidden></p>
    <p class="status" id="status" role="status"></p>
    <form class="email" id="email" hidden>
      <label>To <input id="to" name="to" autocomplete="off"></label>
      <label>Subject <input id="subject" name="subject" autocomplete="off"></label>
      <label>Email <textarea id="body" name="body"></textarea></label>
      <p class="notes" id="notes"></p>
      <button class="primary" type="button" id="copy">Copy email</button>
    </form>
  </main>
  <script>
    const empty = document.querySelector("#empty");
    const strip = document.querySelector("#shots");
    const again = document.querySelector("#again");
    const status = document.querySelector("#status");
    const email = document.querySelector("#email");
    const noteField = document.querySelector("#note");
    const writeButton = document.querySelector("#write");
    const composer = document.querySelector("#composer");
    const toField = document.querySelector("#to");
    const subjectField = document.querySelector("#subject");
    const bodyField = document.querySelector("#body");
    const notes = document.querySelector("#notes");
    const copyButton = document.querySelector("#copy");
    const shots = [];
    let generation = 0;

    function readFile(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
    }

    function setStatus(message, isError) {
      status.textContent = message;
      status.classList.toggle("error", Boolean(isError));
    }

    function renderShots() {
      strip.replaceChildren();
      shots.forEach((shot, index) => {
        const figure = document.createElement("figure");
        figure.className = "thumb";
        const img = document.createElement("img");
        img.src = shot.url;
        img.alt = "Screenshot " + (index + 1);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove";
        remove.textContent = "Remove";
        remove.setAttribute("aria-label", "Remove screenshot " + (index + 1));
        remove.addEventListener("click", () => {
          URL.revokeObjectURL(shot.url);
          shots.splice(index, 1);
          renderShots();
        });
        figure.append(img, remove);
        strip.append(figure);
      });
      const hasShots = shots.length > 0;
      empty.hidden = hasShots;
      strip.hidden = !hasShots;
      again.hidden = !hasShots;
      if (shots.length === 1) {
        again.textContent = "1 screenshot. Press Ctrl+V to add another.";
      } else if (shots.length > 1) {
        again.textContent = shots.length + " screenshots. Press Ctrl+V to add another.";
      }
      writeButton.disabled = !hasShots;
    }

    function addFiles(files) {
      let extra = false;
      for (const file of files) {
        if (!file) continue;
        if (shots.length >= 8) {
          extra = true;
          break;
        }
        shots.push({
          file: file,
          url: URL.createObjectURL(file),
          mediaType: file.type || "image/png"
        });
      }
      renderShots();
      setStatus(extra ? "Paste up to 8 screenshots." : "", extra);
    }

    async function writeDraft() {
      if (!shots.length) {
        setStatus("Paste a screenshot first.", true);
        return;
      }
      const current = ++generation;
      const files = shots.slice();
      email.hidden = true;
      writeButton.disabled = true;
      setStatus("Writing the email…", false);
      const images = [];
      try {
        for (const shot of files) {
          const dataUrl = await readFile(shot.file);
          images.push({
            media_type: shot.mediaType || shot.file.type || "image/png",
            data: String(dataUrl).split(",")[1] || ""
          });
        }
      } catch (error) {
        writeButton.disabled = shots.length === 0;
        setStatus("Could not read that image.", true);
        return;
      }
      if (current !== generation) return;
      let response;
      try {
        response = await fetch("/api/draft", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            note: noteField.value,
            images: images
          })
        });
      } catch (error) {
        if (current !== generation) return;
        writeButton.disabled = shots.length === 0;
        setStatus("Could not reach the drafter.", true);
        return;
      }
      const payload = await response.json().catch(() => ({}));
      if (current !== generation) return;
      writeButton.disabled = shots.length === 0;
      if (!response.ok) {
        setStatus(payload.error || "Could not write the email.", true);
        return;
      }
      toField.value = payload.to || "";
      subjectField.value = payload.subject || "";
      bodyField.value = payload.body || "";
      notes.textContent = payload.notes ? "Notes: " + payload.notes : "";
      email.hidden = false;
      setStatus("", false);
    }

    function filesFromPaste(event) {
      const files = [];
      const items = event.clipboardData && event.clipboardData.items;
      if (items) {
        for (const item of items) {
          if (!item.type || !item.type.startsWith("image/")) continue;
          const file = item.getAsFile();
          if (!file) continue;
          files.push(file.type ? file : new File([file], file.name || "screenshot.png", { type: item.type }));
        }
      }
      const listed = event.clipboardData && event.clipboardData.files;
      if (!files.length && listed) {
        for (const file of listed) {
          if (file.type && file.type.startsWith("image/")) files.push(file);
        }
      }
      const unique = [];
      const seen = new Set();
      for (const file of files) {
        const key = [file.type, file.size].join(":");
        if (seen.has(key)) continue;
        seen.add(key);
        unique.push(file);
      }
      return unique;
    }

    document.addEventListener("paste", (event) => {
      const files = filesFromPaste(event);
      if (!files.length) return;
      event.preventDefault();
      addFiles(files);
    }, true);

    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      writeDraft();
    });

    async function copyText(text) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (error) {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.left = "-9999px";
        document.body.appendChild(helper);
        helper.select();
        let copied = false;
        try {
          copied = document.execCommand("copy");
        } catch (commandError) {
          copied = false;
        }
        helper.remove();
        return copied;
      }
    }

    copyButton.addEventListener("click", async () => {
      const text = [
        "To: " + toField.value.trim(),
        "Subject: " + subjectField.value.trim(),
        "",
        bodyField.value.trim()
      ].join("\\n");
      const copied = await copyText(text);
      copyButton.textContent = copied ? "Copied" : "Could not copy";
      setTimeout(() => { copyButton.textContent = "Copy email"; }, 1500);
    });
  </script>
</body>
</html>
"""


class DraftHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self._send(404, {"error": "Not found"})
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/draft":
            self._send(404, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 48 * 1024 * 1024:
            self._send(400, {"error": "Paste a screenshot first."})
            return
        try:
            incoming = json.loads(self.rfile.read(length).decode("utf-8"))
            images = images_from_payload(incoming)
            note = note_from_payload(incoming)
            tone = incoming.get("tone")
            draft = call_vision(
                build_request(images, note, tone if isinstance(tone, str) else None)
            )
        except DraftError as error:
            self._send(400, {"error": str(error)})
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "Could not read that image."})
            return
        to_name = (draft.get("to_name") or "").strip()
        to_email = (draft.get("to_email") or "").strip()
        if to_name and to_email:
            to_line = f"{to_name} <{to_email}>"
        else:
            to_line = to_name or to_email
        self._send(
            200,
            {
                "to": to_line,
                "subject": (draft.get("subject") or "").strip(),
                "body": (draft.get("body") or "").strip(),
                "notes": (draft.get("notes") or "").strip(),
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int, open_browser: bool) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), DraftHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"Paste screenshots at {url}", flush=True)
    print(f"Share http://YOUR_PUBLIC_IP:{port}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft an email from a screenshot.")
    parser.add_argument("images", nargs="*", help="Screenshot files. Omit to use the clipboard.")
    parser.add_argument("--serve", action="store_true", help="Open the paste page.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the paste page.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    parser.add_argument("--note", default="", help="What the email should do.")
    parser.add_argument("--tone", help="Optional tone, for example 'warm' or 'brief'.")
    parser.add_argument("--json", action="store_true", help="Print the raw JSON draft.")
    args = parser.parse_args()

    if args.serve:
        serve(args.port, open_browser=not args.no_browser)
        return

    try:
        images = [load_image(path) for path in args.images] or [load_image(None)]
        draft = call_vision(build_request(images, args.note, args.tone))
    except DraftError as error:
        raise SystemExit(str(error)) from error
    if args.json:
        json.dump(draft, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    sys.stdout.write(render(draft))


if __name__ == "__main__":
    main()
