# mailreply-agent

Draft a reply to a Gmail conversation. Paste the conversation link, or paste a screenshot that shows that link. The screenshot is used only to read the link. The reply is written from the Gmail message, then sent in that same thread.

**Live page:** [http://52.20.242.94:8765/](http://52.20.242.94:8765/)

**Demo:** [Google Drive](https://drive.google.com/drive/folders/1jm-UYKRabcmkSE3jHmjPP76C5pQ_lzrW)

## Use the page

1. Open the link and unlock Gmail with the server password.
2. Paste a Gmail conversation link, or paste a screenshot that shows one (`Ctrl+V`).
3. Edit the note if you want a different kind of reply. It starts as "What to reply to this".
4. Press **Write email**. The page reads the link, opens that conversation, and drafts from the Gmail message.
5. Edit the draft if needed, then press **Send** or **Copy email**.

A screenshot is searched only for the Gmail link. If the picture has no link, the page stops. It does not write the reply from the text in the picture.

The reply goes to the sender of the latest incoming message, not to everyone on the thread. If a newer message arrives before you send, the page shows it and waits for a new draft. A second click does not send a second copy.

## Run it yourself

Create a virtual environment, install the dependencies, and set the keys in `.env`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env`:

```bash
OPENAI_API_KEY=sk-your-key-here
APP_PASSWORD=choose-a-password
EMAIL_DRAFT_MODEL=gpt-4.1-mini
```

Start the page:

```bash
.venv/bin/python draft_email.py --serve --no-browser
```

On Windows PowerShell, use `.venv\Scripts\python` instead of `.venv/bin/python`.

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The server listens on all interfaces, so on a cloud instance the public link is `http://YOUR_PUBLIC_IP:8765` after inbound TCP port 8765 is allowed.

Optional: `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`.

## Connect Gmail

Paste a link such as `https://mail.google.com/mail/u/0/#inbox/...`. The `/u/0/` part is only a browser profile slot. The app uses the Gmail account you connect.

The id in the link is not a Gmail API id. The app decodes it when the link uses Gmail's `thread-f` form, then asks Gmail whether that thread is in the connected account. If it is not, the app lists conversations and waits for you to choose.

1. In Google Cloud, enable the Gmail API and create an OAuth client (Desktop app). Save the JSON as `client_secret.json`. Do not commit it.
2. Connect the account on a computer with a browser: `.venv/bin/python draft_email.py --gmail-auth`
3. Copy `.gmail_token.json` to the server. Google will not accept `http://52.20.242.94:8765/` as a sign-in redirect.
4. Set `APP_PASSWORD` in `.env`. The public page asks for it before it will read or send Gmail.

Keep `.env`, `.gmail_token.json`, and `client_secret.json` off GitHub.
