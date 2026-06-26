# Odysseus Browser Companion

Load this folder as an unpacked Chrome/Chromium extension:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose "Load unpacked".
4. Select `browser_extension/odysseus`.

The extension does not use stdio or assume localhost. It stores:

- an explicit Odysseus base URL, such as `https://odysseus.malpas.nz` or a LAN URL
- an `ody_...` API token with the `browser_companion` profile

The background service worker is the only extension context that talks to
Odysseus. Content scripts only extract page text from the active tab when the
user presses a popup action, so page credentials are not exposed to websites.

If Odysseus is behind Cloudflare Access, keep the browser logged into the Access
application. Requests use `credentials: include` so the browser profile's Access
cookie can ride along with the Odysseus bearer token.
