# Surfaced iOS

Small native SwiftUI client for the existing `GET /api/scan` JSON API. It does not embed the Python scanner and it does not use a web view.

## What it does

- Enter a website address.
- Call `/api/scan?url=` on a Surfaced server you configure.
- Show a loading state, then the returned overall score, GEO / AEO / reviews / social scores, and prioritized fixes.
- Show validation and network errors, with Retry.
- Server setting is an HTTPS origin only. It starts empty. No production URL is included.

## Server address

Tap **Server** and enter an origin with no path, for example `https://scan.example.com`. The app requests `https://scan.example.com/api/scan?url=…`.

Plain HTTP is rejected. This repository does not document a verified production host, so you point the app at a Surfaced server you run (see the root README). The phone or simulator must be able to reach that HTTPS origin. `http://localhost:8000` will not be accepted.

## Build on a Mac

This project was not compiled here. The Linux environment has no Xcode and no iOS simulator.

1. Use a Mac with Xcode 16 or newer.
2. Open `ios/Surfaced/Surfaced.xcodeproj`.
3. Select the Surfaced target, then Signing & Capabilities, and choose your Team. The bundle id is `app.surfaced.scan`. Change it if that id is unavailable. No signing team is set in the project.
4. Choose an iPhone simulator or a connected device and press Run.
5. In the app, set Server to your HTTPS Surfaced origin, then scan a public website.

That Xcode build and signing step is still required. It was not run.

No app icon image is included. Xcode uses a blank icon until one is added. That does not block the scan flow.

## Parser check

From the repository root:

```bash
python3 ios/validate_api_models.py
```

The script builds a SAMPLE payload with `server.result_to_dict` (the function `/api/scan` serializes with) and checks the Swift `CodingKeys`. It also requests `/api/scan` with no `url` from a local server and checks the error JSON. The fixture `ios/Fixtures/sample-scan-response.json` is that SAMPLE payload. The app does not load it, and a scan is never filled in with it.
