# mailreply-agent

Paste one or more screenshots of an email and get a reply to the sender.

**Live page:** [http://52.20.242.94:8765/](http://52.20.242.94:8765/)

## Use the page

1. Open the link.
2. Paste a screenshot with Ctrl+V. Paste again to add another, up to 8.
3. Edit the note if you want a different kind of reply. It starts as "What to reply to this".
4. Press **Write email**.
5. Edit the draft if needed, then press **Copy email**.

The reply is addressed to the sender in the screenshot, not a rewrite of their message.

## Run it yourself

Set an OpenAI key, then start the page:

```bash
export OPENAI_API_KEY="sk-your-key-here"
python3 draft_email.py --serve
```

On Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"
python draft_email.py --serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The server listens on all interfaces, so on a cloud instance the public link is `http://YOUR_PUBLIC_IP:8765` after inbound TCP port 8765 is allowed.

Optional environment variables:

- `EMAIL_DRAFT_MODEL` defaults to `gpt-4.1-mini`
- `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`

## Reply in a Gmail thread

Paste the conversation link from the browser, for example `https://mail.google.com/mail/u/0/#inbox/...`. The `/u/0/` part is only a browser profile slot. The app uses the Gmail account you connect, and it shows that address so you can confirm it.

The id in the link is not a Gmail API id. The app decodes it when the link uses Gmail's `thread-f` form, then asks Gmail whether that thread is in the connected account. If it is not, the app lists conversations and waits for you to choose. It does not guess.

1. Create a Google Cloud OAuth client (Desktop app) with the Gmail API enabled. Save the JSON as `client_secret.json`. Do not commit it.
2. Install dependencies: `pip install -r requirements.txt`
3. Connect the account: `python draft_email.py --gmail-auth`
4. Set `APP_PASSWORD` on the server. The public page asks for it before it will read or send Gmail.
5. Paste screenshots, paste the Gmail link, press **Find conversation**, then **Write email**. Press **Send** only when the draft is right.

Send replies only to the latest incoming message, in that same thread. If a newer message arrives first, the app shows it and will not send until you write the reply again. A second click does not send a second copy.

Google's sign-in cannot use the raw `http://52.20.242.94:8765/` address as a redirect. Run `--gmail-auth` on a computer with a browser, then copy `.gmail_token.json` to the server. Keep that file, `client_secret.json`, and `APP_PASSWORD` off GitHub.
