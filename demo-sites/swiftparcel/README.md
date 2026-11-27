# SwiftParcel security simulation

SwiftParcel is a fictional parcel-delivery site for controlled PhishDet investigations. The first page looks like a normal tracking experience. Following the demo tracking number reveals a simulated delivery fee and inert account and payment fields.

This is a **security simulation**, not a delivery service. Do not use real credentials or payment information. The mock fields are read-only, the confirmation control sends no data, and the app has no API, database, analytics, or storage.

## Run locally

Requires Node.js 22 or newer and npm.

```sh
npm ci
npm run dev
```

The development server binds to `127.0.0.1` only. Open the local URL printed by Vite. The page starts with `SP-2048-7721`; choose **Track my parcel**, then **Continue to delivery** to see the second experience.

For PhishDet passive-capture testing, serve the built site. The build prerenders the initial React screen and inlines the compiled stylesheet so the landing page remains visible when a scanner disables JavaScript and external resources.

```sh
npm run build
npm run preview
```

Preview also binds to `127.0.0.1`. Production files are written to `dist/`.

When running PhishDet from the repository root, this build is served at `/swiftparcel/`. Open **Visit site** on the PhishDet welcome screen, or select **Use test URL** to fill the scanner input. Generated `dist/` files are committed so the route is available in normal checkouts without a Node build step.

## Docker

Build and bind the container to the host loopback interface:

```sh
docker build -t swiftparcel-simulation .
docker run --rm --name swiftparcel-simulation \
  -p 127.0.0.1:4173:80 swiftparcel-simulation
```

Open `http://127.0.0.1:4173`. Keep the loopback binding when running in the controlled test environment; do not publish this simulation to a public interface. Stop it with `Ctrl+C`.

## Test the journey

```sh
npm test
```

The tests check that the initial page is ordinary, the delivery flow reveals the €1.99 prompt, and mock sensitive fields cannot be edited or submitted.

## Investigation behavior

- The initial state is rendered into the production HTML for a passive screenshot.
- React hydrates that same state and provides the deterministic tracking journey.
- The fee screen appears only after the visitor continues through the tracking flow. No bot detection or scanner-specific behavior is used.
- Inputs on the simulated payment and sign-in screen are read-only and have no form names. The confirmation button only displays an on-page simulation notice.

Run this site only in an isolated, authorized testing environment.
