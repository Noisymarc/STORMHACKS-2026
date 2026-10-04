# Hosting Class Clarity

Render runs the Python backend and serves the website together. The same server
handles the microphone WebSocket, captions, explanations and TiDB saved help.
The deployment configuration is in `render.yaml`; it uses a Free web service.

## Deploy on Render

1. Sign in at https://dashboard.render.com/ and connect the team's GitHub repository.
2. Choose **New > Blueprint**, select `Noisymarc/STORMHACKS-2026`, and use the
   branch containing the reviewed deployment changes. Name the Blueprint Class Clarity.
3. Confirm the service's compute plan is **Free**. Enter the Gemini, ElevenLabs
   and TiDB values in Render's private environment settings. Use the team's
   existing TiDB database name instead of `test` if different. Do not upload `.env`
   to GitHub or copy its values into screenshots or documentation.
4. Deploy and check the service's generated HTTPS URL. Start a microphone session,
   speak English, stop, select a phrase, and request a Japanese explanation/audio.
   Save a phrase and refresh to check the TiDB connection.

For manual Web Service setup, use Python, build command
`pip install -r requirements.txt`, start command `python -m backend.live_app`,
health check `/health`, and `APP_ENV=production` with the same provider/database
settings. Render supplies `PORT`; the server binds to `0.0.0.0` in production.
Use the module launch command so provider clients are initialized.
`/health` checks configuration and server readiness without calling paid APIs;
it does not verify that provider credentials are valid.

Keep `TIDB_CA_PATH` unset to use the host's trusted system certificates. A Windows
certificate path from a local `.env` does not exist on Render. If the database
uses an IP allowlist, authorize the outbound addresses shown by Render for this
service. TiDB stores saved phrases independently of Render's temporary filesystem.

## Connect classclarity.tech

1. In the running service, open **Settings > Custom Domains**, add
   `classclarity.tech`, and read Render's DNS instructions.
2. In the domain provider's DNS settings, apply the records Render requests.
   Use the actual service hostname shown in the dashboard, not an example URL.
   Remove conflicting records for this website only. Preserve unrelated email records.
3. Verify the domain in Render. Wait for DNS verification and the managed HTTPS
   certificate before testing https://classclarity.tech.
4. If you want `www.classclarity.tech`, add it in Render too and follow its records.

Microphone access needs HTTPS on an online site. The page automatically uses
secure WebSockets when opened over HTTPS; no frontend URL changes are needed.

## Demo limits

The Free service sleeps after 15 minutes without incoming HTTP/WebSocket traffic
and takes about a minute to wake up. Open it shortly before the pitch. Active
incoming microphone WebSocket messages count as traffic. Free hosting has monthly
usage limits and can be suspended for unusually high outbound API traffic.
Gemini, ElevenLabs and TiDB usage still draws on those providers' credits.

Auto deployment is off: reviewed code can be deployed manually from Render.
This remains a hackathon demo with browser identifiers rather than account login.
Anyone with its public URL can use its configured API credits; stop the service
after the demo if ongoing public use is not intended.

Official references: https://render.com/docs/free,
https://render.com/docs/blueprint-spec, https://render.com/docs/custom-domains.
