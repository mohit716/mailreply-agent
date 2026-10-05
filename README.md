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
